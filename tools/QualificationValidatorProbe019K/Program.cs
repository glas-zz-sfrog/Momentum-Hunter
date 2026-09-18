using System.Diagnostics;
using System.Text.Json;

namespace MomentumHunter.ContinuousServiceHost;

internal sealed class WriterValidationProtocol
{
    internal string? Validate(byte[] output, byte[] error, int childPid, long childBirth,
        int parentPid, long parentBirth) => null;
}

internal static class Program
{
    private static int _checks;

    private static void Require(bool condition, string name)
    {
        if (!condition) throw new InvalidOperationException("FAILED: " + name);
        _checks++;
    }

    private static ProcessStartInfo Child(string python, string work, string source, string code,
        bool withHook)
    {
        var info = new ProcessStartInfo(python)
        {
            WorkingDirectory = work,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        info.ArgumentList.Add("-B");
        info.ArgumentList.Add("-c");
        info.ArgumentList.Add(code);
        info.Environment["PYTHONDONTWRITEBYTECODE"] = "1";
        info.Environment.Remove("MH_QUALIFICATION_DIAGNOSTIC_ROOT");
        if (withHook) info.Environment["PYTHONPATH"] = source;
        else info.Environment.Remove("PYTHONPATH");
        return info;
    }

    private static async Task<ValidatorResult> Run(string root, string name, ProcessStartInfo info,
        TimeSpan timeout, bool diagnosticOnly, int streamLimit = 65536,
        CancellationToken caller = default)
    {
        return await QualificationValidator.RunAsync(info, Path.Combine(root, name), timeout, caller,
            streamLimit: streamLimit, diagnosticOnly: diagnosticOnly);
    }

    private static string[] Stages(string root, string name) =>
        File.Exists(Path.Combine(root, name, "python-stages.log"))
            ? File.ReadAllLines(Path.Combine(root, name, "python-stages.log")) : [];

    private static string[] Events(string root, string name) =>
        File.ReadAllLines(Path.Combine(root, name, "events.jsonl"))
            .Select(line => JsonDocument.Parse(line).RootElement.GetProperty("stage").GetString()!).ToArray();

    private static async Task<int> Main(string[] args)
    {
        if (args.Length != 2) throw new ArgumentException("Expected Python executable and source root.");
        var python = Path.GetFullPath(args[0]);
        var source = Path.GetFullPath(args[1]);
        if (!File.Exists(python) || !File.Exists(Path.Combine(source, "sitecustomize.py")))
            throw new InvalidOperationException("Frozen test inputs are missing.");
        var root = Path.Combine(Path.GetTempPath(), "mh-019k-validator-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var plain = await Run(root, "plain", Child(python, root, source, "print('OK')", false),
                TimeSpan.FromSeconds(5), false);
            Require(plain.Accepted && plain.StdoutBytes > 0, "uninstrumented acceptance unchanged");
            Require(!File.Exists(Path.Combine(root, "plain", "python-stages.log")), "plain has no trace");

            var traced = await Run(root, "traced", Child(python, root, source,
                "import sitecustomize; sitecustomize.argus_trace('NORMAL_CHILD'); print('OK')", true),
                TimeSpan.FromSeconds(5), true);
            Require(traced.Accepted && traced.StdoutBytes == plain.StdoutBytes, "diagnostic success");
            Require(Stages(root, "traced").Any(line => line.Contains("NORMAL_CHILD")), "durable child stage");
            Require(Events(root, "traced").Contains("DIAGNOSTIC_RESULT"), "durable parent result");

            var missing = await Run(root, "missing-hook", Child(python, root, source, "print('OK')", false),
                TimeSpan.FromSeconds(5), true);
            Require(!missing.Accepted && missing.Failure == "DIAGNOSTIC_TRACE_NOT_ARMED",
                "missing hook fails closed");

            var writerSite = Path.Combine(Path.GetDirectoryName(Path.GetDirectoryName(python))!,
                "Lib", "site-packages");
            var isolated = new ProcessStartInfo(python)
            {
                WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
            };
            foreach (var argument in new[] { "-I", "-S", "-B", "-X", "utf8", "-c",
                "import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(0,sys.argv[2]);" +
                "from momentum_hunter.continuous_production import main;print('WRITER_IMPORT_OK')",
                source, writerSite })
                isolated.ArgumentList.Add(argument);
            isolated.Environment.Remove("MH_QUALIFICATION_DIAGNOSTIC_ROOT");
            var writerBootstrap = await Run(root, "writer-isolated-bootstrap", isolated,
                TimeSpan.FromSeconds(10), false);
            Require(writerBootstrap.Accepted &&
                File.ReadAllText(Path.Combine(root, "writer-isolated-bootstrap", "stdout.bin"))
                    .Contains("WRITER_IMPORT_OK"), "isolated writer bootstrap remains usable");
            Require(!File.Exists(Path.Combine(root, "writer-isolated-bootstrap", "python-stages.log")),
                "writer bootstrap does not require diagnostic hook");

            var timerWatch = Stopwatch.StartNew();
            var timeout = await Run(root, "timeout", Child(python, root, source,
                "import sitecustomize,time; sitecustomize.argus_trace('BLOCKED_CHILD'); time.sleep(5)", true),
                TimeSpan.FromSeconds(1), true);
            timerWatch.Stop();
            Require(!timeout.Accepted && timeout.CancellationSource == "TIMER" && timeout.CleanupComplete,
                "unchanged timer cancellation and cleanup");
            Require(timerWatch.Elapsed < TimeSpan.FromSeconds(3), "diagnostics do not extend timer cleanup");
            Require(Events(root, "timeout").Contains("CHILD_CREATE_REQUEST"), "durable launch request");
            Require(Events(root, "timeout").Contains("PARENT_WAIT_ENTER"), "durable parent wait entry");
            Require(Events(root, "timeout").Contains("PARENT_WAIT_EXIT"), "durable parent wait exit");
            Require(Events(root, "timeout").Contains("TIMEOUT_POSTMORTEM"), "parent postmortem after kill");
            Require(Stages(root, "timeout").Any(line => line.Contains("BLOCKED_CHILD")),
                "timeout retains last child stage");

            var subprocessWait = await Run(root, "subprocess-wait", Child(python, root, source,
                "import sitecustomize,os,subprocess,sys; sitecustomize.argus_trace('SUBPROCESS_WAIT'); " +
                "env=os.environ.copy(); env.pop('MH_QUALIFICATION_DIAGNOSTIC_ROOT',None); " +
                "p=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(5)'],env=env); " +
                "print(p.pid,flush=True); p.wait()", true), TimeSpan.FromSeconds(1), true);
            Require(!subprocessWait.Accepted && subprocessWait.CancellationSource == "TIMER" &&
                subprocessWait.CleanupComplete, "subprocess wait times out and cleans up");
            Require(Stages(root, "subprocess-wait").Any(line => line.Contains("SUBPROCESS_WAIT")),
                "subprocess wait stage is durable");
            var descendantText = File.ReadAllText(Path.Combine(root, "subprocess-wait", "stdout.bin")).Trim();
            Require(int.TryParse(descendantText, out var descendantPid), "subprocess identity captured");
            var descendantGone = false;
            for (var retry = 0; retry < 20 && !descendantGone; retry++)
            {
                try { using var descendant = Process.GetProcessById(descendantPid); descendantGone = descendant.HasExited; }
                catch (ArgumentException) { descendantGone = true; }
                if (!descendantGone) await Task.Delay(100);
            }
            Require(descendantGone, "subprocess descendant terminated with child tree");

            var flooded = await Run(root, "flooded", Child(python, root, source,
                "import sys; sys.stdout.write('x'*100000); sys.stdout.flush()", true),
                TimeSpan.FromSeconds(5), true, streamLimit: 1024);
            Require(!flooded.Accepted && flooded.CancellationSource == "STDOUT_LIMIT",
                "output limit remains blocking");
            Require(flooded.CleanupComplete, "output-flood cleanup");

            using var caller = new CancellationTokenSource(TimeSpan.FromSeconds(1));
            var cancelled = await Run(root, "caller", Child(python, root, source,
                "import time; time.sleep(5)", true), TimeSpan.FromSeconds(5), true, caller: caller.Token);
            Require(!cancelled.Accepted && cancelled.CancellationSource == "CALLER", "caller cancellation");
            Require(cancelled.CleanupComplete, "caller cleanup");

            var invalid = Child(Path.Combine(root, "missing-python.exe"), root, source, "print('OK')", true);
            var failedLaunch = await Run(root, "failed-launch", invalid, TimeSpan.FromSeconds(5), true);
            Require(!failedLaunch.Accepted && failedLaunch.Failure is not null, "launch failure visible");

            var summary = new { status = "PASS", checks = _checks, testRoot = root,
                acceptanceTimeoutChanged = false, serviceActions = 0, providerContact = false };
            Console.WriteLine(JsonSerializer.Serialize(summary));
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception);
            return 1;
        }
    }
}
