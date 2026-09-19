using System.Diagnostics;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;

namespace MomentumHunter.ContinuousServiceHost;

internal sealed class WriterValidationProtocol
{
    internal string? Validate(byte[] output, byte[] error, int childPid, long childBirth,
        int parentPid, long parentBirth) => null;
}

internal static class Program
{
    private static void Require(bool condition, string name)
    {
        if (!condition) throw new InvalidOperationException("FAILED: " + name);
    }

    private static ProcessStartInfo Child(string python, string source, params string[] args)
    {
        var info = new ProcessStartInfo(python) { WorkingDirectory = source,
            UseShellExecute = false, CreateNoWindow = true };
        foreach (var arg in args) info.ArgumentList.Add(arg);
        info.Environment.Remove("PYTHONPATH");
        info.Environment.Remove("PYTHONHOME");
        info.Environment["PYTHONDONTWRITEBYTECODE"] = "1";
        return info;
    }

    private static string Activation(string path)
    {
        foreach (var line in File.ReadLines(Path.Combine(path, "events.jsonl")))
        {
            using var document = JsonDocument.Parse(line);
            if (document.RootElement.GetProperty("stage").GetString() == "DIAGNOSTIC_ACTIVATION_RESULT")
                return document.RootElement.GetProperty("detail").GetProperty("classification").GetString()!;
        }
        throw new InvalidDataException("Activation classification missing.");
    }

    private static JsonElement Event(string path, string stage)
    {
        foreach (var line in File.ReadLines(Path.Combine(path, "events.jsonl")))
        {
            using var document = JsonDocument.Parse(line);
            if (document.RootElement.GetProperty("stage").GetString() == stage)
                return document.RootElement.Clone();
        }
        throw new InvalidDataException("Missing event: " + stage);
    }

    private static async Task<(string PipeName, int ChildPid)> WaitForLaunchIdentity(string path)
    {
        var deadline = Stopwatch.StartNew();
        while (deadline.Elapsed < TimeSpan.FromSeconds(5))
        {
            string? pipeName = null;
            int? childPid = null;
            try
            {
                using var stream = new FileStream(Path.Combine(path, "events.jsonl"),
                    FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                using var reader = new StreamReader(stream);
                foreach (var line in reader.ReadToEnd().Split('\n').Where(line => line.Length > 0))
                {
                    using var document = JsonDocument.Parse(line);
                    var stage = document.RootElement.GetProperty("stage").GetString();
                    if (stage == "DIAGNOSTIC_ARMED")
                        pipeName = document.RootElement.GetProperty("detail").GetProperty("pipeName").GetString();
                    else if (stage == "H1_CHILD_PROCESS_CREATED")
                        childPid = document.RootElement.GetProperty("detail").GetProperty("pid").GetInt32();
                }
            }
            catch (IOException) { }
            catch (JsonException) { }
            if (pipeName is not null && childPid is not null)
                return (pipeName, childPid.Value);
            await Task.Delay(10);
        }
        throw new TimeoutException("Launch identity was not durably recorded.");
    }

    private static async Task<int> Main(string[] args)
    {
        if (args.Length != 2) throw new ArgumentException("Expected staged Python and source root.");
        var exerciseParentStdinContention =
            Environment.GetEnvironmentVariable("MH_019M_TEST_PARENT_STDIN_CONTENTION") == "1";
        var pendingParentRead = exerciseParentStdinContention ?
            Task.Run(() => Console.In.ReadLine()) : null;
        var python = Path.GetFullPath(args[0]);
        var source = Path.GetFullPath(args[1]);
        var root = Path.Combine(Path.GetTempPath(), "mh-019m-parent-probe-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var exactPath = Path.Combine(root, "exact-module");
            var exact = await QualificationValidator.RunAsync(
                Child(python, source, "-B", "-m", "momentum_hunter.continuous_production",
                    "--config", Path.Combine(root, "missing.json"), "--print-install-plan"),
                exactPath, TimeSpan.FromSeconds(30), default,
                diagnosticOnly: true, requireHandshake: true);
            Require(exact.ExitCode != 0 && exact.CancellationSource is null,
                "invalid config does not become activation failure");
            Require(!exerciseParentStdinContention || pendingParentRead is { IsCompleted: false },
                "parent stdin contention remains active during child validation");
            Require(Activation(exactPath) == "DIAGNOSTIC_ACTIVE", "real module path activates");
            _ = Event(exactPath, "CHILD_STANDARD_INPUT_CLOSED");
            _ = Event(exactPath, "H0_PARENT_ABOUT_TO_CREATE_CHILD");
            var childEvent = Event(exactPath, "H1_CHILD_PROCESS_CREATED");
            var childPid = childEvent.GetProperty("detail").GetProperty("pid").GetInt32();
            Require(childPid > 0 &&
                childEvent.GetProperty("detail").GetProperty("commandSha256").GetString()!.Length == 64 &&
                childEvent.GetProperty("detail").GetProperty("environmentSha256").GetString()!.Length == 64,
                "child creation identity is durably bound");
            var actor = Event(exactPath, "DIAGNOSTIC_STAGE_ACTOR_BOUND").GetProperty("detail");
            Require(actor.GetProperty("Pid").GetInt32() > 0 &&
                actor.GetProperty("ImageSha256").GetString()!.Length == 64 &&
                (actor.GetProperty("Pid").GetInt32() == childPid ||
                 actor.GetProperty("ParentPid").GetInt32() == childPid),
                "stage actor is the child or its direct venv descendant");
            var stageText = File.ReadAllLines(Path.Combine(exactPath, "python-stages.log"));
            var stageNames = stageText.Select(line => line.Split('|')[2]).ToArray();
            var required = new[] { "H2_PYTHON_RUNTIME_STARTED", "H3_DIAGNOSTIC_BOOTSTRAP_ACTIVE",
                "H4_TARGET_MODULE_ENTRY_REACHED", "H5_PRINT_INSTALL_PLAN_ENTRY_REACHED" };
            var indices = required.Select(stage => Array.IndexOf(stageNames, stage)).ToArray();
            Require(indices.All(index => index >= 0) && indices.SequenceEqual(indices.Order()),
                "Python handshake is complete and ordered");

            var noSitePath = Path.Combine(root, "no-site");
            var noSite = await QualificationValidator.RunAsync(
                Child(python, source, "-S", "-B", "-m", "momentum_hunter.continuous_production",
                    "--config", Path.Combine(root, "missing.json"), "--print-install-plan"),
                noSitePath, TimeSpan.FromSeconds(30), default,
                diagnosticOnly: true, requireHandshake: true);
            Require(!noSite.Accepted && Activation(noSitePath) == "DIAGNOSTIC_NOT_ACTIVE",
                "suppressed site hook fails visibly");

            var wrongModulePath = Path.Combine(root, "wrong-module");
            var wrongModule = await QualificationValidator.RunAsync(
                Child(python, source, "-B", "-m", "json.tool", "--help"),
                wrongModulePath, TimeSpan.FromSeconds(30), default,
                diagnosticOnly: true, requireHandshake: true);
            Require(!wrongModule.Accepted &&
                Activation(wrongModulePath) == "DIAGNOSTIC_ACTIVATION_PARTIAL" &&
                wrongModule.Failure == "DIAGNOSTIC_ACTIVATION_FAILURE:H4_TARGET_MODULE_ENTRY_REACHED",
                "wrong module cannot masquerade as target activation");

            var foreignPath = Path.Combine(root, "foreign-stage-actor");
            var foreignWriter = Task.Run(async () =>
            {
                while (!Directory.Exists(foreignPath)) await Task.Delay(5);
                var launch = await WaitForLaunchIdentity(foreignPath);
                var shortName = launch.PipeName.Replace(@"\\.\pipe\", "", StringComparison.Ordinal);
                using var pipe = new NamedPipeClientStream(".", shortName, PipeDirection.InOut,
                    PipeOptions.Asynchronous);
                await pipe.ConnectAsync(5000);
                var stamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() * 1000000;
                var payload = $"{stamp}|{launch.ChildPid}|H2_PYTHON_RUNTIME_STARTED\n" +
                    $"{stamp + 1}|{launch.ChildPid}|H3_DIAGNOSTIC_BOOTSTRAP_ACTIVE\n";
                try
                {
                    var bytes = Encoding.ASCII.GetBytes(payload);
                    await pipe.WriteAsync(bytes);
                    await pipe.FlushAsync();
                }
                catch (IOException) { }
            });
            var foreign = await QualificationValidator.RunAsync(
                Child(python, source, "-S", "-B", "-c", "import time;time.sleep(15)"),
                foreignPath, TimeSpan.FromSeconds(30), default,
                diagnosticOnly: true, requireHandshake: true);
            await foreignWriter;
            Require(!foreign.Accepted && foreign.CancellationSource == "DIAGNOSTIC_ACTIVATION_FAILURE" &&
                Activation(foreignPath) == "DIAGNOSTIC_NOT_ACTIVE" &&
                new FileInfo(Path.Combine(foreignPath, "python-stages.log")).Length == 0,
                "foreign writer cannot satisfy the handshake by claiming the real child PID");
            Require(Event(foreignPath, "DIAGNOSTIC_PIPE_FAILURE").GetProperty("detail")
                .GetProperty("Message").GetString() == "STAGE_ACTOR_PREDATES_CHILD",
                "pipe client identity, not the claimed row PID, controls attribution");

            var stalledPath = Path.Combine(root, "stalled-startup");
            var timer = Stopwatch.StartNew();
            var stalled = await QualificationValidator.RunAsync(
                Child(python, source, "-S", "-B", "-c", "import time;time.sleep(15)"),
                stalledPath, TimeSpan.FromSeconds(30), default,
                diagnosticOnly: true, requireHandshake: true);
            timer.Stop();
            Require(stalled.CancellationSource == "DIAGNOSTIC_ACTIVATION_FAILURE" &&
                stalled.CleanupComplete && timer.Elapsed < TimeSpan.FromSeconds(9),
                "missing H2/H3 stops before the authoritative 30-second timer");
            Require(Activation(stalledPath) == "DIAGNOSTIC_NOT_ACTIVE", "stalled startup classified");

            var descendantPath = Path.Combine(root, "descendant-cleanup");
            var descendantMarker = Path.Combine(root, "descendant-pid.txt");
            var script = "import pathlib,subprocess,sys,time;" +
                "p=subprocess.Popen([sys.executable,'-S','-c','import time;time.sleep(20)']);" +
                "pathlib.Path(" + JsonSerializer.Serialize(descendantMarker) + ").write_text(str(p.pid));" +
                "time.sleep(20)";
            var descendantResult = await QualificationValidator.RunAsync(
                Child(python, source, "-S", "-B", "-c", script),
                descendantPath, TimeSpan.FromSeconds(30), default,
                diagnosticOnly: true, requireHandshake: true);
            Require(File.Exists(descendantMarker), "test descendant was actually created");
            var descendantPid = int.Parse(File.ReadAllText(descendantMarker));
            var descendantExited = false;
            try
            {
                using var descendant = Process.GetProcessById(descendantPid);
                descendantExited = descendant.HasExited;
                if (!descendantExited)
                {
                    descendant.Kill(entireProcessTree: true);
                    descendant.WaitForExit(5000);
                }
            }
            catch (ArgumentException) { descendantExited = true; }
            Require(descendantResult.CancellationSource == "DIAGNOSTIC_ACTIVATION_FAILURE" &&
                descendantResult.CleanupComplete && descendantExited,
                "activation failure terminates the owned descendant tree");

            Console.WriteLine(JsonSerializer.Serialize(new { status = "PASS", root,
                checks = 14, parentStdinContention = exerciseParentStdinContention,
                exactActivation = Activation(exactPath),
                missingActivation = Activation(noSitePath),
                stalledActivation = Activation(stalledPath),
                stalledSeconds = timer.Elapsed.TotalSeconds,
                acceptanceTimeoutSeconds = 30, serviceActions = 0, providerContact = false }));
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception);
            return 1;
        }
    }
}
