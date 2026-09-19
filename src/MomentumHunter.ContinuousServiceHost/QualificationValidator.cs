using System.Diagnostics;
using System.ComponentModel;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace MomentumHunter.ContinuousServiceHost;

internal sealed record ValidatorResult(int? ExitCode, string? CancellationSource,
    long StdoutBytes, long StderrBytes, bool CleanupComplete, string? Failure)
{
    public bool? ProtocolAccepted { get; init; }
    public string? ProtocolFailure { get; init; }
    public bool Accepted => ExitCode == 0 && CancellationSource is null && Failure is null
        && CleanupComplete && StdoutBytes is > 0 and <= 65536 && StderrBytes is >= 0 and <= 65536
        && ProtocolFailure is null && (ProtocolAccepted ?? (StderrBytes == 0));
}

// Diagnostics do not confer service/admission authority or change the child command.
internal static class QualificationValidator
{
    internal static async Task<ValidatorResult> RunAsync(ProcessStartInfo info, string root,
        TimeSpan timeout, CancellationToken caller, int streamLimit = 65536,
        WriterValidationProtocol? writerProtocol = null, bool diagnosticOnly = false,
        bool requireOuterJob = false, bool requireHandshake = false)
    {
        if (timeout <= TimeSpan.Zero || timeout > TimeSpan.FromMinutes(2) || streamLimit is < 1 or > 1048576)
            throw new ArgumentOutOfRangeException(nameof(timeout));
        if (requireHandshake && !diagnosticOnly)
            throw new ArgumentException("A diagnostic handshake requires diagnostic mode.");
        if (Directory.Exists(root) || File.Exists(root)) throw new IOException("Validator evidence already exists.");
        Directory.CreateDirectory(root);
        if (diagnosticOnly) info.Environment["MH_QUALIFICATION_DIAGNOSTIC_ROOT"] = Path.GetFullPath(root);
        if (requireHandshake) info.Environment["MH_QUALIFICATION_DIAGNOSTIC_PARENT_ACK"] = "REQUIRED";
        var diagnosticPipeName = requireHandshake ?
            "MomentumHunter-Qualification-" + Guid.NewGuid().ToString("N") : null;
        using var diagnosticPipe = requireHandshake ? new NamedPipeServerStream(
            diagnosticPipeName!,
            PipeDirection.InOut, 1, PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly) : null;
        if (diagnosticPipe is not null)
            info.Environment["MH_QUALIFICATION_DIAGNOSTIC_PIPE"] = @"\\.\pipe\" + diagnosticPipeName;
        else
            info.Environment.Remove("MH_QUALIFICATION_DIAGNOSTIC_PIPE");
        var stagePath = Path.Combine(root, "python-stages.log");
        var stackPath = Path.Combine(root, "python-stacks.log");
        using var authenticatedStages = requireHandshake ? new FileStream(stagePath,
            FileMode.CreateNew, FileAccess.Write, FileShare.Read) : null;
        using var events = new FileStream(Path.Combine(root, "events.jsonl"), FileMode.CreateNew, FileAccess.Write, FileShare.Read);
        var sync = new object();
        void Record(string stage, object detail)
        {
            lock (sync)
            {
                var bytes = JsonSerializer.SerializeToUtf8Bytes(new { stage, at = DateTimeOffset.UtcNow, detail });
                events.Write(bytes);
                events.WriteByte(10);
                events.Flush(true);
            }
        }
        using var launcher = Process.GetCurrentProcess();
        if (requireOuterJob)
        {
            var inJob = false;
            var queried = OperatingSystem.IsWindows() &&
                IsProcessInJob(launcher.Handle, IntPtr.Zero, out inJob);
            Record("PROCESS_JOB_CHECK", new { launcherPid = launcher.Id, diagnosticOnly,
                queried, inJob = queried && inJob });
            if (!diagnosticOnly || !queried || !inJob)
                throw new InvalidOperationException("Diagnostic runtime requires a preassigned process job.");
            Record("PROCESS_JOB_PRESENT_BEFORE_CHILD_CREATE", new { launcherPid = launcher.Id,
                exactJobIdentity = "EXTERNAL_RECORDER_ATTESTATION_REQUIRED" });
        }
        var environment = new Dictionary<string, string?>();
        foreach (var key in new[] { "PATH", "SystemRoot", "TEMP", "TMP", "USERPROFILE", "HOME",
            "PYTHONHOME", "PYTHONPATH", "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE", "MOMENTUM_HUNTER_CONTINUOUS_SERVICE_MODE",
            "MH_QUALIFICATION_DIAGNOSTIC_ROOT", "MH_QUALIFICATION_DIAGNOSTIC_PIPE" })
            if (info.Environment.TryGetValue(key, out var value)) environment[key] = value;
        Record("LAUNCH_INTENT", new { launcherPid = launcher.Id, launcherBirth = launcher.StartTime.ToUniversalTime(),
            launcherImage = Environment.ProcessPath, childImage = info.FileName, argv = info.ArgumentList.ToArray(),
            workingDirectory = info.WorkingDirectory, environment, timeoutSeconds = timeout.TotalSeconds,
            descendantScope = "CHILD_TREE_TERMINATION_ON_FAILURE; external observer must independently prove descendant chronology" });
        if (diagnosticOnly) Record("DIAGNOSTIC_ARMED", new { stagePath, stackPath,
            pipeName = diagnosticPipeName, stageCustody = requireHandshake ? "PARENT_OWNED_PIPE_CLIENT_PID_BOUND" : "LOCAL_ONLY",
            stackTimerSeconds = 20,
            acceptanceTimeoutSeconds = timeout.TotalSeconds });
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardInput = true;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        using var child = new Process { StartInfo = info };
        using var diagnosticJob = diagnosticOnly && OperatingSystem.IsWindows() ? new DiagnosticChildJob() : null;
        using var output = new FileStream(Path.Combine(root, "stdout.bin"), FileMode.CreateNew, FileAccess.ReadWrite, FileShare.Read);
        using var error = new FileStream(Path.Combine(root, "stderr.bin"), FileMode.CreateNew, FileAccess.ReadWrite, FileShare.Read);
        var interrupt = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        string? cancellation = null, failure = null;
        int? exit = null;
        long stdoutCount = 0, stderrCount = 0;
        int childPid = 0;
        long childBirth = 0;
        bool started = false, cleanup = false;
        using var stopReads = new CancellationTokenSource();
        Task<long>? stdout = null, stderr = null;
        Task<StageActorBinding?>? activationWatch = null;
        Task? pipeCapture = null;
        StageActorBinding? stageActor = null;
        void Cancel(string source)
        {
            lock (sync)
            {
                if (interrupt.Task.IsCompleted) return;
                Record("CANCELLATION", new { source, initiatorPid = launcher.Id });
                interrupt.TrySetResult(source);
            }
        }
        using var timer = new CancellationTokenSource();
        using var callerRegistration = caller.Register(() => Cancel("CALLER"));
        using var timerRegistration = timer.Token.Register(() => Cancel("TIMER"));
        async Task<long> Drain(Stream input, FileStream sink, string name)
        {
            var buffer = new byte[4096];
            long count = 0;
            try
            {
                int length;
                while ((length = await input.ReadAsync(buffer, stopReads.Token)) != 0)
                {
                    var retained = (int)Math.Min(length, Math.Max(0, streamLimit - count));
                    if (retained > 0)
                    {
                        sink.Write(buffer, 0, retained);
                        sink.Flush(true);
                    }
                    count += length;
                    if (count > streamLimit) Cancel(name + "_LIMIT");
                }
                sink.Flush(true);
                Record("STREAM_CLOSED", new { name, totalBytes = count, retainedBytes = sink.Length });
                return count;
            }
            catch (Exception ex)
            {
                Cancel(name + "_IO_FAILURE");
                Record("STREAM_FAILURE", new { name, type = ex.GetType().Name, ex.Message });
                throw;
            }
        }
        try
        {
            // A pre-canceled caller must never launch a child.
            caller.ThrowIfCancellationRequested();
            var executableSha256 = diagnosticOnly ? Hash(info.FileName) : null;
            var commandSha256 = diagnosticOnly ? HashBytes(JsonSerializer.SerializeToUtf8Bytes(info.ArgumentList.ToArray())) : null;
            var environmentSha256 = diagnosticOnly ? HashBytes(JsonSerializer.SerializeToUtf8Bytes(
                info.Environment.OrderBy(item => item.Key, StringComparer.OrdinalIgnoreCase).ToArray())) : null;
            if (diagnosticOnly)
            {
                Record("H0_PARENT_ABOUT_TO_CREATE_CHILD", new { executable = info.FileName,
                    executableSha256, commandSha256, environmentSha256 });
                Record("CHILD_CREATE_REQUEST", new { executable = info.FileName });
            }
            caller.ThrowIfCancellationRequested();
            timer.CancelAfter(timeout);
            if (!child.Start()) throw new InvalidOperationException("Validator start returned false.");
            started = true;
            child.StandardInput.Close();
            childPid = child.Id;
            childBirth = child.StartTime.ToUniversalTime().ToFileTimeUtc();
            diagnosticJob?.Assign(child);
            if (diagnosticOnly) Record("CHILD_STANDARD_INPUT_CLOSED", new {
                pid = childPid, policy = "DEDICATED_EOF_PIPE" });
            if (diagnosticOnly)
                Record("H1_CHILD_PROCESS_CREATED", new { pid = childPid, birth = childBirth,
                    executable = info.FileName, executableSha256, commandSha256, environmentSha256 });
            Record("CHILD_STARTED", new { pid = child.Id, birth = child.StartTime.ToUniversalTime() });
            stdout = Drain(child.StandardOutput.BaseStream, output, "STDOUT");
            stderr = Drain(child.StandardError.BaseStream, error, "STDERR");
            if (requireHandshake)
                pipeCapture = CaptureAuthenticatedStagesAsync(diagnosticPipe!, authenticatedStages!,
                    child, info.FileName, Record, Cancel);
            if (requireHandshake)
                activationWatch = WatchActivationAsync(stagePath, root, child, info.FileName,
                    interrupt.Task, Record, Cancel);
            {
                var exited = child.WaitForExitAsync();
                if (diagnosticOnly) Record("PARENT_WAIT_ENTER", new { childPid, wait = "CHILD_EXIT_OR_INTERRUPT" });
                await Task.WhenAny(exited, interrupt.Task);
                if (interrupt.Task.IsCompleted)
                {
                    cancellation = await interrupt.Task;
                    Record("TERMINATION_REQUESTED", new { pid = child.Id, birth = child.StartTime.ToUniversalTime(), tree = true });
                    diagnosticJob?.Terminate();
                    if (!child.HasExited) child.Kill(entireProcessTree: true);
                }
                await exited.WaitAsync(TimeSpan.FromSeconds(10));
                if (diagnosticOnly) Record("PARENT_WAIT_EXIT", new { childPid, interrupted = interrupt.Task.IsCompleted });
                if (diagnosticOnly && cancellation == "TIMER")
                {
                    double? childCpuMilliseconds = null;
                    try { childCpuMilliseconds = child.TotalProcessorTime.TotalMilliseconds; }
                    catch (InvalidOperationException) { }
                    catch (System.ComponentModel.Win32Exception) { }
                    Record("TIMEOUT_POSTMORTEM", new { pid = child.Id, exitCode = child.ExitCode,
                        childCpuMilliseconds, stdoutRetainedBytes = output.Length,
                        stderrRetainedBytes = error.Length,
                        stageBytes = File.Exists(stagePath) ? new FileInfo(stagePath).Length : 0,
                        stackBytes = File.Exists(stackPath) ? new FileInfo(stackPath).Length : 0 });
                }
                // An inherited pipe must not hold this host forever after root exit.
                if (diagnosticOnly) Record("PIPE_DRAIN_WAIT_ENTER", new { childPid,
                    stdoutRetainedBytes = output.Length, stderrRetainedBytes = error.Length });
                var drained = Task.WhenAll(stdout, stderr);
                if (diagnosticOnly && !drained.IsCompleted &&
                    await Task.WhenAny(drained, interrupt.Task) == interrupt.Task)
                {
                    cancellation = await interrupt.Task;
                    Record("PIPE_DRAIN_INTERRUPTED", new { childPid, cancellation });
                    diagnosticJob?.Terminate();
                }
                await drained.WaitAsync(TimeSpan.FromSeconds(10));
                if (diagnosticOnly) Record("PIPE_DRAIN_WAIT_EXIT", new { childPid });
                diagnosticJob?.Terminate();
                stdoutCount = await stdout;
                stderrCount = await stderr;
                if (interrupt.Task.IsCompleted) cancellation = await interrupt.Task;
            }
            exit = child.ExitCode;
            cleanup = true;
            Record("CHILD_EXITED", new { pid = child.Id, birth = child.StartTime.ToUniversalTime(), exitCode = exit,
                windowsExitStatusHex = unchecked((uint)exit.Value).ToString("X8"),
                ntStatusInterpretation = "RAW_EXIT_STATUS_ONLY_NOT_INFERRED" });
        }
        catch (Exception ex)
        {
            failure = ex.GetType().Name + ": " + ex.Message;
            if (ex is OperationCanceledException && !started) { cancellation = "CALLER_BEFORE_LAUNCH"; Cancel(cancellation); }
            Record("VALIDATOR_FAILURE", new { type = ex.GetType().Name, ex.Message, started });
            if (started)
            {
                try
                {
                    diagnosticJob?.Terminate();
                    if (!child.HasExited) child.Kill(entireProcessTree: true);
                    await child.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(10));
                    exit = child.ExitCode;
                }
                catch (Exception stop) { Record("CLEANUP_UNPROVEN", new { type = stop.GetType().Name, stop.Message }); }
            }
            // Never claim successful cleanup after an output/exit observation failure.
            cleanup = !started;
        }
        finally
        {
            stopReads.Cancel();
            if (pipeCapture is not null)
            {
                try { await pipeCapture.WaitAsync(TimeSpan.FromSeconds(7)); }
                catch (Exception ex)
                {
                    cleanup = false;
                    Record("DIAGNOSTIC_PIPE_UNPROVEN", new { type = ex.GetType().Name, ex.Message });
                }
            }
            if (activationWatch is not null)
            {
                try { stageActor = await activationWatch.WaitAsync(TimeSpan.FromSeconds(7)); }
                catch (Exception ex)
                {
                    cleanup = false;
                    Record("ACTIVATION_WATCH_UNPROVEN", new { type = ex.GetType().Name, ex.Message });
                }
            }
            var streamTasks = new[] { stdout, stderr }.Where(task => task is not null)
                .Select(task => (Task)task!).ToArray();
            try
            {
                await Task.WhenAll(streamTasks).WaitAsync(TimeSpan.FromSeconds(10));
            }
            catch (Exception ex)
            {
                cleanup = false;
                Record("STREAM_CLEANUP_UNPROVEN", new { type = ex.GetType().Name, ex.Message });
            }
        }
        output.Flush(true);
        error.Flush(true);
        if (diagnosticOnly)
        {
            var stageBytes = File.Exists(stagePath) ? new FileInfo(stagePath).Length : 0;
            var stackExists = File.Exists(stackPath);
            var stages = ReadStages(stagePath);
            var required = new[] { "H2_PYTHON_RUNTIME_STARTED", "H3_DIAGNOSTIC_BOOTSTRAP_ACTIVE",
                "H4_TARGET_MODULE_ENTRY_REACHED", "H5_PRINT_INSTALL_PLAN_ENTRY_REACHED" };
            var missing = required.Where(stage => !stages.Names.Contains(stage)).ToArray();
            var activation = stages.Conflict is not null ? "DIAGNOSTIC_CONFLICT" :
                missing.Length == 0 ? "DIAGNOSTIC_ACTIVE" :
                stages.Names.Count == 0 ? "DIAGNOSTIC_NOT_ACTIVE" : "DIAGNOSTIC_ACTIVATION_PARTIAL";
            if (requireHandshake && stages.Names.Contains("H2_PYTHON_RUNTIME_STARTED") &&
                stageActor is null) activation = "DIAGNOSTIC_ACTOR_UNBOUND";
            Record("DIAGNOSTIC_ACTIVATION_RESULT", new { classification = activation,
                stagePid = stages.Pid, stageActor, missing, stages.Conflict });
            Record("DIAGNOSTIC_RESULT", new { stageBytes, stackExists,
                stackBytes = stackExists ? new FileInfo(stackPath).Length : 0 });
            if (requireHandshake && (missing.Length > 0 || stages.Conflict is not null || stageActor is null) &&
                failure is null && cancellation is null)
                failure = "DIAGNOSTIC_ACTIVATION_FAILURE:" + (stages.Conflict ??
                    (missing.Length > 0 ? missing[0] : "ACTOR_UNBOUND"));
            else if (exit == 0 && cancellation is null && failure is null && (stageBytes == 0 || !stackExists))
                failure = "DIAGNOSTIC_TRACE_NOT_ARMED";
        }
        var result = new ValidatorResult(exit, cancellation, stdoutCount, stderrCount, cleanup, failure);
        if (writerProtocol is not null)
        {
            string? protocolFailure = "PROCESS_NOT_SUCCESSFUL";
            try
            {
                if (exit == 0 && cancellation is null && failure is null && cleanup &&
                    stdoutCount is > 0 and <= 65536 && stderrCount is > 0 and <= 65536)
                    protocolFailure = writerProtocol.Validate(Snapshot(output), Snapshot(error), childPid, childBirth,
                        launcher.Id, launcher.StartTime.ToUniversalTime().ToFileTimeUtc());
            }
            catch (Exception ex)
            {
                protocolFailure = "PROTOCOL_OBSERVATION_FAILURE_" + ex.GetType().Name;
            }
            result = result with { ProtocolAccepted = protocolFailure is null, ProtocolFailure = protocolFailure };
        }
        Record("TERMINAL", result);
        var summary = JsonSerializer.SerializeToUtf8Bytes(new { result, result.Accepted,
            stdoutSha256 = Hash(Path.Combine(root, "stdout.bin")), stderrSha256 = Hash(Path.Combine(root, "stderr.bin")),
            diagnostic = diagnosticOnly ? new {
                stageSha256 = File.Exists(stagePath) ? Hash(stagePath) : null,
                stackSha256 = File.Exists(stackPath) ? Hash(stackPath) : null,
                stageBytes = File.Exists(stagePath) ? new FileInfo(stagePath).Length : 0,
                stackBytes = File.Exists(stackPath) ? new FileInfo(stackPath).Length : 0,
            } : null,
            durability = "STREAMS_AND_TERMINAL_FLUSHED_BEFORE_PROCESS_HANDLE_DISPOSAL" });
        using var receipt = new FileStream(Path.Combine(root, "result.json"), FileMode.CreateNew, FileAccess.Write, FileShare.Read);
        receipt.Write(summary);
        receipt.Flush(true);
        return result;
    }

    private static string Hash(string path)
    {
        using var stream = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        return Convert.ToHexString(SHA256.HashData(stream));
    }

    private static string HashBytes(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes));

    private sealed record StageSnapshot(HashSet<string> Names, int? Pid, string? Conflict);
    private sealed record StageActorBinding(int Pid, long Birth, int? ParentPid,
        string Image, string ImageSha256, string ExpectedImage);

    private static async Task CaptureAuthenticatedStagesAsync(NamedPipeServerStream pipe,
        FileStream stageSink, Process child, string executable,
        Action<string, object> record, Action<string> cancel)
    {
        try
        {
            using var connectionLimit = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            await pipe.WaitForConnectionAsync(connectionLimit.Token);
            if (!GetNamedPipeClientProcessId(pipe.SafePipeHandle.DangerousGetHandle(), out var nativePid) ||
                nativePid == 0 || nativePid > int.MaxValue)
                throw new InvalidDataException("DIAGNOSTIC_PIPE_CLIENT_PID_UNAVAILABLE");
            var actor = BindStageActor((int)nativePid, child, executable);
            record("DIAGNOSTIC_PIPE_CLIENT_BOUND", actor);
            var row = new List<byte>(256);
            var one = new byte[1];
            while (true)
            {
                var read = await pipe.ReadAsync(one);
                if (read == 0) break;
                if (one[0] != (byte)'\n')
                {
                    if (row.Count == 255) throw new InvalidDataException("DIAGNOSTIC_PIPE_ROW_TOO_LONG");
                    row.Add(one[0]);
                    continue;
                }
                var bytes = row.ToArray();
                var fields = Encoding.ASCII.GetString(bytes).Split('|');
                if (fields.Length != 3 || !long.TryParse(fields[0], out var at) || at <= 0 ||
                    !int.TryParse(fields[1], out var reportedPid) || reportedPid != actor.Pid ||
                    fields[2].Length == 0 ||
                    fields[2].Any(ch => !(ch is >= 'A' and <= 'Z' or >= '0' and <= '9' or '_')))
                    throw new InvalidDataException("DIAGNOSTIC_PIPE_INVALID_STAGE_ROW");
                stageSink.Write(bytes);
                stageSink.WriteByte((byte)'\n');
                stageSink.Flush(true);
                await pipe.WriteAsync(new byte[] { (byte)'1' });
                await pipe.FlushAsync();
                row.Clear();
            }
            if (row.Count != 0) throw new InvalidDataException("DIAGNOSTIC_PIPE_PARTIAL_ROW");
            record("DIAGNOSTIC_PIPE_CLOSED", new { actor.Pid, stageBytes = stageSink.Length });
        }
        catch (Exception ex)
        {
            record("DIAGNOSTIC_PIPE_FAILURE", new { type = ex.GetType().Name, ex.Message });
            cancel("DIAGNOSTIC_ACTIVATION_FAILURE");
        }
    }

    private static StageSnapshot ReadStages(string path)
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        if (!File.Exists(path)) return new StageSnapshot(names, null, null);
        try
        {
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete);
            if (stream.Length > 65536) return new StageSnapshot(names, null, "STAGE_FILE_TOO_LARGE");
            using var reader = new StreamReader(stream, Encoding.ASCII);
            var content = reader.ReadToEnd();
            if (content.Length == 0) return new StageSnapshot(names, null, null);
            int? pid = null;
            var handshake = new[] { "H2_PYTHON_RUNTIME_STARTED", "H3_DIAGNOSTIC_BOOTSTRAP_ACTIVE",
                "H4_TARGET_MODULE_ENTRY_REACHED", "H5_PRINT_INSTALL_PLAN_ENTRY_REACHED" };
            var nextHandshake = 0;
            foreach (var line in content.Split('\n').SkipLast(1))
            {
                var fields = line.TrimEnd('\r').Split('|');
                if (fields.Length != 3 || !long.TryParse(fields[0], out var at) || at <= 0 ||
                    !int.TryParse(fields[1], out var rowPid) || rowPid <= 0 ||
                    fields[2].Length == 0 || fields[2].Any(ch => !(ch is >= 'A' and <= 'Z' or >= '0' and <= '9' or '_')))
                    return new StageSnapshot(names, pid, "INVALID_STAGE_ROW");
                if (pid is not null && pid != rowPid)
                    return new StageSnapshot(names, pid, "MULTIPLE_STAGE_ACTORS");
                if (handshake.Contains(fields[2]))
                {
                    if (nextHandshake >= handshake.Length || fields[2] != handshake[nextHandshake])
                        return new StageSnapshot(names, pid, "HANDSHAKE_OUT_OF_ORDER");
                    nextHandshake++;
                }
                pid = rowPid;
                names.Add(fields[2]);
            }
            if (!content.EndsWith('\n')) return new StageSnapshot(names, pid, "PARTIAL_STAGE_ROW");
            return new StageSnapshot(names, pid, null);
        }
        catch (IOException) { return new StageSnapshot(names, null, "STAGE_READ_IO_FAILURE"); }
        catch (UnauthorizedAccessException) { return new StageSnapshot(names, null, "STAGE_READ_DENIED"); }
    }

    private static async Task<StageActorBinding?> WatchActivationAsync(string stagePath, string root,
        Process child, string executable, Task interrupted,
        Action<string, object> record, Action<string> cancel)
    {
        var deadline = Stopwatch.StartNew();
        while (deadline.Elapsed < TimeSpan.FromSeconds(5))
        {
            var stages = ReadStages(stagePath);
            if (stages.Conflict is not null)
            {
                record("DIAGNOSTIC_ACTIVATION_FAILURE", new { stages.Conflict });
                cancel("DIAGNOSTIC_ACTIVATION_FAILURE");
                return null;
            }
            if (stages.Names.Contains("H2_PYTHON_RUNTIME_STARTED") &&
                stages.Names.Contains("H3_DIAGNOSTIC_BOOTSTRAP_ACTIVE"))
            {
                try
                {
                    if (stages.Pid is null) throw new InvalidDataException("STAGE_PID_MISSING");
                    var binding = BindStageActor(stages.Pid.Value, child, executable);
                    record("DIAGNOSTIC_STAGE_ACTOR_BOUND", binding);
                    var ack = Encoding.ASCII.GetBytes("ARGUS_019M_PARENT_ATTESTED_V1|" + binding.Pid);
                    using (var output = new FileStream(Path.Combine(root,
                        "parent-attestation-" + binding.Pid + ".ok"), FileMode.CreateNew,
                        FileAccess.Write, FileShare.Read))
                    {
                        output.Write(ack);
                        output.Flush(true);
                    }
                    return binding;
                }
                catch (Exception ex)
                {
                    record("DIAGNOSTIC_ACTOR_BINDING_FAILURE", new { type = ex.GetType().Name, ex.Message,
                        stagePid = stages.Pid, childPid = child.Id });
                    cancel("DIAGNOSTIC_ACTIVATION_FAILURE");
                    return null;
                }
            }
            if (interrupted.IsCompleted || child.HasExited) return null;
            await Task.Delay(50);
        }
        record("DIAGNOSTIC_ACTIVATION_FAILURE", new { reason = "H2_H3_NOT_OBSERVED_WITHIN_5_SECONDS" });
        cancel("DIAGNOSTIC_ACTIVATION_FAILURE");
        return null;
    }

    private static StageActorBinding BindStageActor(int stagePid, Process child, string executable)
    {
        using var actor = Process.GetProcessById(stagePid);
        if (actor.HasExited) throw new InvalidDataException("STAGE_ACTOR_EXITED_BEFORE_BINDING");
        var childBirth = child.StartTime.ToUniversalTime().ToFileTimeUtc();
        var birth = actor.StartTime.ToUniversalTime().ToFileTimeUtc();
        if (birth < childBirth) throw new InvalidDataException("STAGE_ACTOR_PREDATES_CHILD");
        int? parentPid = stagePid == child.Id ? null : GetParentProcessId(stagePid);
        if (stagePid != child.Id && parentPid != child.Id)
            throw new InvalidDataException("STAGE_ACTOR_NOT_DIRECT_CHILD");
        if (stagePid == child.Id && birth != childBirth)
            throw new InvalidDataException("STAGE_CHILD_BIRTH_CHANGED");
        var image = ProcessImage(actor);
        var expected = stagePid == child.Id ? Path.GetFullPath(executable) : ExpectedVenvBase(executable);
        if (!Path.GetFullPath(image).Equals(expected, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("STAGE_ACTOR_IMAGE_MISMATCH");
        if (actor.HasExited) throw new InvalidDataException("STAGE_ACTOR_EXITED_DURING_BINDING");
        return new StageActorBinding(stagePid, birth, parentPid, image, Hash(image), expected);
    }

    private static string ExpectedVenvBase(string executable)
    {
        var scripts = Directory.GetParent(Path.GetFullPath(executable)) ??
            throw new InvalidDataException("VENV_SCRIPTS_ROOT_MISSING");
        if (!scripts.Name.Equals("Scripts", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("VENV_SCRIPTS_ROOT_MISMATCH");
        var venv = scripts.Parent ?? throw new InvalidDataException("VENV_ROOT_MISSING");
        var homes = File.ReadAllLines(Path.Combine(venv.FullName, "pyvenv.cfg"))
            .Where(line => line.StartsWith("home = ", StringComparison.OrdinalIgnoreCase)).ToArray();
        if (homes.Length != 1) throw new InvalidDataException("VENV_HOME_AMBIGUOUS");
        var home = Path.GetFullPath(homes[0][7..].Trim());
        return Path.Combine(home, "python.exe");
    }

    private static string ProcessImage(Process process)
    {
        var image = new StringBuilder(32768);
        uint length = (uint)image.Capacity;
        if (!QueryFullProcessImageNameW(process.Handle, 0, image, ref length))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "STAGE_PROCESS_IMAGE_QUERY_FAILED");
        return image.ToString();
    }

    private static int GetParentProcessId(int pid)
    {
        var snapshot = CreateToolhelp32Snapshot(0x00000002, 0);
        if (snapshot == new IntPtr(-1))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "PROCESS_SNAPSHOT_FAILED");
        try
        {
            var entry = new ProcessEntry32 { Size = (uint)Marshal.SizeOf<ProcessEntry32>() };
            if (!Process32FirstW(snapshot, ref entry))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "PROCESS_SNAPSHOT_EMPTY");
            do
            {
                if (entry.ProcessId == (uint)pid) return checked((int)entry.ParentProcessId);
            } while (Process32NextW(snapshot, ref entry));
            throw new InvalidDataException("STAGE_ACTOR_NOT_IN_PROCESS_SNAPSHOT");
        }
        finally { CloseHandle(snapshot); }
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct ProcessEntry32
    {
        public uint Size;
        public uint Usage;
        public uint ProcessId;
        public IntPtr DefaultHeapId;
        public uint ModuleId;
        public uint Threads;
        public uint ParentProcessId;
        public int BasePriority;
        public uint Flags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string ExeFile;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint processId);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool Process32FirstW(IntPtr snapshot, ref ProcessEntry32 entry);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool Process32NextW(IntPtr snapshot, ref ProcessEntry32 entry);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool QueryFullProcessImageNameW(IntPtr process, uint flags,
        StringBuilder image, ref uint length);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetNamedPipeClientProcessId(IntPtr pipe, out uint clientProcessId);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);

    private static byte[] Snapshot(FileStream stream)
    {
        if (stream.Length > 65536) throw new InvalidDataException("Validator output bound exceeded.");
        stream.Position = 0;
        var bytes = new byte[(int)stream.Length];
        stream.ReadExactly(bytes);
        return bytes;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool IsProcessInJob(IntPtr process, IntPtr job, out bool result);

    private sealed class DiagnosticChildJob : IDisposable
    {
        private IntPtr _handle;
        private bool _terminated;

        internal DiagnosticChildJob()
        {
            _handle = CreateJobObjectW(IntPtr.Zero, null);
            if (_handle == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        }

        internal void Assign(Process process)
        {
            if (!AssignProcessToJobObject(_handle, process.Handle))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "Diagnostic child job assignment failed.");
        }

        internal void Terminate()
        {
            if (_handle != IntPtr.Zero && !TerminateJobObject(_handle, 1))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "Diagnostic child job termination failed.");
            _terminated = true;
        }

        public void Dispose()
        {
            if (_handle == IntPtr.Zero) return;
            try { if (!_terminated) Terminate(); }
            finally { CloseHandle(_handle); _handle = IntPtr.Zero; }
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateJobObjectW(IntPtr securityAttributes, string? name);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateJobObject(IntPtr job, uint exitCode);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr handle);
    }
}
