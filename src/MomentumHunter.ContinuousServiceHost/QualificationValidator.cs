using System.Diagnostics;
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
        WriterValidationProtocol? writerProtocol = null, bool diagnosticOnly = false)
    {
        if (timeout <= TimeSpan.Zero || timeout > TimeSpan.FromMinutes(2) || streamLimit is < 1 or > 1048576)
            throw new ArgumentOutOfRangeException(nameof(timeout));
        if (Directory.Exists(root) || File.Exists(root)) throw new IOException("Validator evidence already exists.");
        Directory.CreateDirectory(root);
        if (diagnosticOnly) info.Environment["MH_QUALIFICATION_DIAGNOSTIC_ROOT"] = Path.GetFullPath(root);
        var stagePath = Path.Combine(root, "python-stages.log");
        var stackPath = Path.Combine(root, "python-stacks.log");
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
        var environment = new Dictionary<string, string?>();
        foreach (var key in new[] { "PATH", "SystemRoot", "TEMP", "TMP", "USERPROFILE", "HOME",
            "PYTHONHOME", "PYTHONPATH", "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE", "MOMENTUM_HUNTER_CONTINUOUS_SERVICE_MODE",
            "MH_QUALIFICATION_DIAGNOSTIC_ROOT" })
            if (info.Environment.TryGetValue(key, out var value)) environment[key] = value;
        Record("LAUNCH_INTENT", new { launcherPid = launcher.Id, launcherBirth = launcher.StartTime.ToUniversalTime(),
            launcherImage = Environment.ProcessPath, childImage = info.FileName, argv = info.ArgumentList.ToArray(),
            workingDirectory = info.WorkingDirectory, environment, timeoutSeconds = timeout.TotalSeconds,
            descendantScope = "CHILD_TREE_TERMINATION_ON_FAILURE; external observer must independently prove descendant chronology" });
        if (diagnosticOnly) Record("DIAGNOSTIC_ARMED", new { stagePath, stackPath, stackTimerSeconds = 20,
            acceptanceTimeoutSeconds = timeout.TotalSeconds });
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        using var child = new Process { StartInfo = info };
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
        void Cancel(string source)
        {
            lock (sync)
            {
                if (interrupt.Task.IsCompleted) return;
                Record("CANCELLATION", new { source, initiatorPid = launcher.Id });
                interrupt.TrySetResult(source);
            }
        }
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
            if (diagnosticOnly) Record("CHILD_CREATE_REQUEST", new { executable = info.FileName });
            if (!child.Start()) throw new InvalidOperationException("Validator start returned false.");
            started = true;
            childPid = child.Id;
            childBirth = child.StartTime.ToUniversalTime().ToFileTimeUtc();
            Record("CHILD_STARTED", new { pid = child.Id, birth = child.StartTime.ToUniversalTime() });
            stdout = Drain(child.StandardOutput.BaseStream, output, "STDOUT");
            stderr = Drain(child.StandardError.BaseStream, error, "STDERR");
            using (var timer = new CancellationTokenSource(timeout))
            using (caller.Register(() => Cancel("CALLER")))
            using (timer.Token.Register(() => Cancel("TIMER")))
            {
                var exited = child.WaitForExitAsync();
                if (diagnosticOnly) Record("PARENT_WAIT_ENTER", new { childPid, wait = "CHILD_EXIT_OR_INTERRUPT" });
                await Task.WhenAny(exited, interrupt.Task);
                if (interrupt.Task.IsCompleted)
                {
                    cancellation = await interrupt.Task;
                    Record("TERMINATION_REQUESTED", new { pid = child.Id, birth = child.StartTime.ToUniversalTime(), tree = true });
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
                await Task.WhenAll(stdout, stderr).WaitAsync(TimeSpan.FromSeconds(10));
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
            foreach (var streamTask in new[] { stdout, stderr })
            {
                if (streamTask is null) continue;
                try { await streamTask; }
                catch (Exception) { cleanup = false; }
            }
        }
        output.Flush(true);
        error.Flush(true);
        if (diagnosticOnly)
        {
            var stageBytes = File.Exists(stagePath) ? new FileInfo(stagePath).Length : 0;
            var stackExists = File.Exists(stackPath);
            Record("DIAGNOSTIC_RESULT", new { stageBytes, stackExists,
                stackBytes = stackExists ? new FileInfo(stackPath).Length : 0 });
            if (exit == 0 && cancellation is null && failure is null && (stageBytes == 0 || !stackExists))
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

    private static byte[] Snapshot(FileStream stream)
    {
        if (stream.Length > 65536) throw new InvalidDataException("Validator output bound exceeded.");
        stream.Position = 0;
        var bytes = new byte[(int)stream.Length];
        stream.ReadExactly(bytes);
        return bytes;
    }
}
