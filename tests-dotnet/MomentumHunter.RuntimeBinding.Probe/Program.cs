using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using MomentumHunter.ContinuousServiceHost;

// This probe invokes the production assembly, never a copied launch algorithm.
// It does not start the BackgroundService/validator, SCM, or domain runtime.
var mode = args[0];
var configPath = Path.GetFullPath(args[1]);
var repository = Path.GetFullPath(args[2]);
var python = Path.GetFullPath(args[3]);
var caseRoot = Path.GetFullPath(args[4]);
var config = JsonNode.Parse(File.ReadAllBytes(configPath))!.AsObject();
var options = ContinuousServiceOptions.Create([
    "--role", "runtime", "--repository-root", repository, "--python-executable", python,
    "--config", configPath, "--instance", config["host"]!["instanceId"]!.GetValue<string>(),
    "--console-control", "true"]);
var flags = BindingFlags.Instance | BindingFlags.NonPublic;
object? Call(object target, string name, params object[] values)
{
    try { return target.GetType().GetMethod(name, flags)!.Invoke(target, values); }
    catch (TargetInvocationException ex) { throw ex.InnerException!; }
}
void Set(object target, string name, object? value) => target.GetType().GetField(name, flags)!.SetValue(target, value);
object? Get(object target, string name) => target.GetType().GetField(name, flags)!.GetValue(target);
ContinuousProcessWorker Worker(ContinuousServiceOptions value) => new(value, new ProbeLogger(), new ProbeLifetime());
IDisposable? Open(ContinuousProcessWorker worker, string role)
{
    var image = (IDisposable?)Call(worker, role == "writer" ? "OpenWriterImage" : "OpenRuntimeImage");
    Set(worker, role == "writer" ? "_writerImage" : "_runtimeImage", image);
    return image;
}
object Command(ContinuousProcessWorker worker, string method)
{
    var info = (ProcessStartInfo)Call(worker, method)!;
    return new { info.FileName, arguments = info.ArgumentList.ToArray(), info.WorkingDirectory,
        info.UseShellExecute, info.CreateNoWindow, info.RedirectStandardInput,
        info.RedirectStandardOutput, info.RedirectStandardError,
        diagnosticRoot = info.Environment.ContainsKey("MH_QUALIFICATION_DIAGNOSTIC_ROOT"),
        diagnosticPipe = info.Environment.ContainsKey("MH_QUALIFICATION_DIAGNOSTIC_PIPE"),
        credentialKeys = info.Environment.Keys.Where(k => System.Text.RegularExpressions.Regex.IsMatch(k,
            "SCHWAB|FINVIZ|ALPACA|IBKR|MH_CANARY|API_KEY|API_SECRET|OAUTH|ACCESS_TOKEN|REFRESH_TOKEN",
            System.Text.RegularExpressions.RegexOptions.IgnoreCase)).ToArray() };
}
bool WriteDenied(string path)
{
    try { using var file = new FileStream(path, FileMode.Open, FileAccess.Write, FileShare.ReadWrite | FileShare.Delete); return false; }
    catch (IOException) { return true; }
}
bool Alive(int pid, long birth)
{
    try { using var process = Process.GetProcessById(pid); return !process.HasExited && process.StartTime.ToUniversalTime().ToFileTimeUtc() == birth; }
    catch (ArgumentException) { return false; }
}
var result = new JsonObject { ["mode"] = mode, ["scope"] = "NONPRIVILEGED_COMPILED_LAUNCH_NOT_PHYSICAL_RUNTIME_ACCEPTANCE" };
try
{
    if (mode == "matrix")
    {
        var rows = new JsonObject();
        foreach (var (label, value) in new (string, ContinuousServiceOptions)[] {
            ("runtime-console", options),
            ("runtime-scm", options with { ConsoleControl = false }),
            ("runtime-live", options with { Qualification = false, ConsoleControl = false }),
            ("runtime-legacy", options with { Qualification = false, ConsoleControl = false }),
            ("science-selection-only", options with { Role = "science" }),
            ("writer", options with { Role = "writer", ConsoleControl = false,
                PythonExecutable = Path.Combine(config["installRoot"]!.GetValue<string>(), "python-base", "python.exe") }) })
        {
            using var worker = Worker(value);
            using var image = Open(worker, value.Role);
            rows[label] = JsonSerializer.SerializeToNode(new { imageBound = image is not null,
                child = Command(worker, "CreateChildStartInfo"), validator = Command(worker, "CreateQualificationStartInfo") });
        }
        result["rows"] = rows;
    }
    else
    {
        using var worker = Worker(options);
        using var image = mode == "redirector" ? null : Open(worker, "runtime");
        result["childCommand"] = JsonSerializer.SerializeToNode(Command(worker, "CreateChildStartInfo"));
        if (mode != "image-check")
        {
            var type = typeof(ContinuousProcessWorker).Assembly.GetType("MomentumHunter.ContinuousServiceHost.HostProcessGeneration")!;
            using var generation = (IDisposable)Activator.CreateInstance(type, configPath, "runtime")!;
            Set(worker, "_generation", generation);
            var generationPath = Path.Combine(config["hostStateRoot"]!.GetValue<string>(), "runtime", "generation.json");
            if (mode == "publication-failure")
            {
                File.Move(generationPath, Path.Combine(caseRoot, "starting-generation.json"));
                Directory.CreateDirectory(generationPath);
            }
            using var cancellation = new CancellationTokenSource();
            var running = (Task)Call(worker, "RunChildOnceAsync", cancellation.Token)!;
            var process = (Process?)Get(worker, "_process");
            int? childPid = process?.Id;
            long? childBirth = process?.StartTime.ToUniversalTime().ToFileTimeUtc();
            if (File.Exists(generationPath))
            {
                var identity = JsonNode.Parse(File.ReadAllBytes(generationPath))!.AsObject();
                result["startedGeneration"] = identity.DeepClone();
                switch (mode)
                {
                    case "wrong-pid": identity["childPid"] = identity["supervisorPid"]!.DeepClone(); identity["childBirth"] = identity["supervisorBirth"]!.DeepClone(); break;
                    case "wrong-birth": identity["childBirth"] = identity["childBirth"]!.GetValue<long>() + 1; break;
                    case "wrong-supervisor-birth": identity["supervisorBirth"] = identity["supervisorBirth"]!.GetValue<long>() + 1; break;
                    case "wrong-generation": identity["generation"] = Guid.NewGuid().ToString("D"); break;
                    case "wrong-fingerprint": identity["hostFingerprint"] = new string('f', 64); break;
                }
                if (mode == "missing-generation") File.Delete(generationPath);
                else File.WriteAllText(generationPath, identity.ToJsonString());
            }
            File.WriteAllText(Path.Combine(caseRoot, "release"), "TEST_FIXTURE_ONLY");
            var ready = Path.Combine(caseRoot, "child-observation.json");
            var deadline = Stopwatch.StartNew();
            while (!running.IsCompleted && !File.Exists(ready) && deadline.Elapsed < TimeSpan.FromSeconds(20))
                await Task.Delay(20);
            var source = Path.Combine(repository, "momentum_hunter", "continuous_production.py");
            result["leaseHeldBeforeStop"] = image is not null && WriteDenied(source);
            cancellation.Cancel();
            try { await running.WaitAsync(TimeSpan.FromSeconds(45)); result["workerResult"] = "EXIT_0"; }
            catch (Exception ex) { result["workerResult"] = ex.GetType().Name + ":" + ex.Message; }
            if (File.Exists(ready)) result["childObservation"] = JsonNode.Parse(File.ReadAllBytes(ready));
            var preAdmission = Path.Combine(caseRoot, "pre-admission.json");
            if (File.Exists(preAdmission)) result["preAdmission"] = JsonNode.Parse(File.ReadAllBytes(preAdmission));
            if (File.Exists(generationPath)) result["terminalGeneration"] = JsonNode.Parse(File.ReadAllBytes(generationPath));
            result["retainedChildAlive"] = childPid is not null && childBirth is not null && Alive(childPid.Value, childBirth.Value);
            result["leaseHeldAfterExit"] = image is not null && WriteDenied(source);
            image?.Dispose();
            result["leaseReleased"] = !WriteDenied(source);
        }
    }
    result["status"] = "OBSERVED";
}
catch (Exception ex)
{
    result["status"] = "REJECTED";
    result["error"] = ex.GetType().Name + ":" + ex.Message;
}
Console.WriteLine(result.ToJsonString());

sealed class ProbeLifetime : IHostApplicationLifetime
{
    public CancellationToken ApplicationStarted => CancellationToken.None;
    public CancellationToken ApplicationStopping => CancellationToken.None;
    public CancellationToken ApplicationStopped => CancellationToken.None;
    public void StopApplication() { }
}
sealed class ProbeLogger : ILogger<ContinuousProcessWorker>
{
    public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;
    public bool IsEnabled(LogLevel level) => true;
    public void Log<TState>(LogLevel level, EventId id, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
        => Console.Error.WriteLine(formatter(state, exception));
}
