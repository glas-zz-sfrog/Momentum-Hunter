using System.Diagnostics;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;
using MomentumHunter.AutomationService;

if (args.Length != 5) throw new ArgumentException("mode root python host barrier");
var mode = args[0]; var root = Path.GetFullPath(args[1]);
if (!root.StartsWith(Path.GetTempPath(), StringComparison.OrdinalIgnoreCase)
    || !Path.GetFileName(root).StartsWith("MH-Prechild-", StringComparison.Ordinal)
    || !Directory.Exists(root) || File.GetAttributes(root).HasFlag(FileAttributes.ReparsePoint))
    throw new InvalidOperationException("DISPOSABLE_PROBE_ROOT_REQUIRED");
var python = Path.GetFullPath(args[2]); var host = Path.GetFullPath(args[3]); var barrier = args[4];
using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(90));
void Emit(object value) { Console.WriteLine(JsonSerializer.Serialize(value)); Console.Out.Flush(); }
async Task Hold(string stage, object? identity = null)
{
    Emit(new { stage, identity, pid = Environment.ProcessId });
    if (barrier == stage)
    {
        var command = await Console.In.ReadLineAsync(timeout.Token);
        if (command != "continue") throw new InvalidOperationException("PROBE_ABORT");
    }
}

if (mode == "decision-host")
{
    var info = new ProcessStartInfo(python) { WorkingDirectory = root, UseShellExecute = false };
    foreach (var item in new[] { "-B", "-m", "momentum_hunter.automation_supervisor", "run", "--manifest", Path.Combine(root, "manifest.json") })
        info.ArgumentList.Add(item);
    using var gate = await RetryLaunchGate.OpenAsync(Path.Combine(root, "launch-contract.json"), info, timeout.Token);
    using var commitTarget = WindowsContainedProcess.CreateSuspended(info);
    await gate.AdmitResumeAsync(commitTarget, timeout.Token);
    await gate.MonitorAsync(commitTarget, timeout.Token, stage => Hold(stage.ToString(), commitTarget.Identity).GetAwaiter().GetResult());
    return;
}

if (mode == "controller")
{
    Directory.CreateDirectory(Path.Combine(root, "momentum_hunter"));
    File.WriteAllText(Path.Combine(root, "momentum_hunter", "__init__.py"), "");
    File.WriteAllText(Path.Combine(root, "momentum_hunter", "automation_supervisor.py"),
        "open('first.txt','x').write('first')\nimport subprocess,sys,time\nsubprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(120)'],creationflags=8)\ntime.sleep(120)\n");
    var manifest = Path.Combine(root, "manifest.json"); File.WriteAllText(manifest, "{}");
    var info = new ProcessStartInfo(python) { WorkingDirectory = root, UseShellExecute = false };
    foreach (var item in new[] { "-B", "-m", "momentum_hunter.automation_supervisor", "run", "--manifest", manifest }) info.ArgumentList.Add(item);
    if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
    using var self = Process.GetCurrentProcess();
    var files = RetryLaunchGate.RequiredStaticFiles(info, host).ToDictionary(p => p,
        p => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(p))));
    using var controller = new RetryControllerSession(Path.Combine(root, "launch-contract.json"), info,
        WindowsIdentity.GetCurrent().User!.Value, self.SessionId, files, TimeSpan.FromMinutes(2));
    await Hold("before-host");
    var start = new ProcessStartInfo(host) { UseShellExecute = false, CreateNoWindow = true,
        WorkingDirectory = root, RedirectStandardOutput = true, RedirectStandardError = true };
    foreach (var item in new[] { "--repository-root", root, "--python-executable", python, "--manifest", manifest,
        "--launch-contract", controller.ContractPath }) start.ArgumentList.Add(item);
    using var service = Process.Start(start) ?? throw new InvalidOperationException("HOST_START_FAILED");
    var stdout = service.StandardOutput.ReadToEndAsync(); var stderr = service.StandardError.ReadToEndAsync();
    try
    {
        await Hold("host-waiting", new { service.Id, Created = service.StartTime.ToUniversalTime().ToFileTimeUtc() });
        await controller.AdmitAsync(ProcessTopologyIdentity.Capture(service.Id, service.StartTime.ToUniversalTime().ToFileTimeUtc()), timeout.Token);
        // Wait only for the already-contained fixture's declared child, never to establish custody.
        while (controller.MemberPids().Count < 4) await Task.Delay(10, timeout.Token);
        var identities = controller.MemberPids().Select(pid =>
        { using var process = Process.GetProcessById(pid); return new { Pid = pid, Created = process.StartTime.ToUniversalTime().ToFileTimeUtc() }; }).ToArray();
        await Hold("running-family", identities);
        controller.Abort();
        Emit(new { stage = "quiesced", remaining = controller.MemberPids().Count });
    }
    finally
    {
        if (!service.HasExited) service.Kill();
        await service.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
        File.WriteAllText(Path.Combine(root, "host-stdout.txt"), await stdout);
        File.WriteAllText(Path.Combine(root, "host-stderr.txt"), await stderr);
    }
    return;
}

var child = "open('child-'+str(__import__('os').getpid()),'x').write('first');import time;time.sleep(120)";
var childLiteral = JsonSerializer.Serialize(child);
var spawn = "subprocess.Popen([sys.executable,'-B','-c'," + childLiteral + "],creationflags=8)";
var body = mode switch
{
    "immediate" => spawn,
    "multiple" => "children=[" + spawn + " for _ in range(5)]",
    "grandchild" => "subprocess.Popen([sys.executable,'-B','-c'," + JsonSerializer.Serialize("import subprocess,sys,time;" + spawn + ";time.sleep(120)") + "])",
    "rapid" => "children=[subprocess.Popen([sys.executable,'-B','-c','pass']) for _ in range(20)]\n[p.wait() for p in children]\n" + spawn,
    "native" => "subprocess.Popen([r'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe','-NoProfile','-NonInteractive','-Command','[Threading.Thread]::Sleep(120000)'],creationflags=0x08000000)",
    "breakaway" => "try:\n " + spawn.Replace("creationflags=8", "creationflags=0x01000000") + "\nexcept OSError as e:\n open('breakaway.txt','x').write(str(e.winerror))\nelse:\n raise Exception('BREAKAWAY_ACCEPTED')",
    "parent-exit" => spawn + ";sys.exit(0)",
    "idle" => "pass",
    _ => throw new ArgumentException("UNKNOWN_PROBE_MODE")
};
var code = "open('first.txt','x').write('first')\nimport subprocess,sys,time\n" + body + "\ntime.sleep(120)";
var targetInfo = new ProcessStartInfo(python) { WorkingDirectory = root, UseShellExecute = false };
foreach (var item in new[] { "-B", "-c", code }) targetInfo.ArgumentList.Add(item);
using var target = WindowsContainedProcess.CreateSuspended(targetInfo,
    stage => { Hold(stage.ToString()).GetAwaiter().GetResult(); });
await Hold("target-suspended", target.Identity);
target.Resume(stage => Hold(stage.ToString()).GetAwaiter().GetResult());
while (!File.Exists(Path.Combine(root, "first.txt"))) await Task.Delay(10, timeout.Token);
if (mode == "breakaway")
{
    while (!File.Exists(Path.Combine(root, "breakaway.txt"))) await Task.Delay(10, timeout.Token);
    if (File.ReadAllText(Path.Combine(root, "breakaway.txt")) != "5") throw new InvalidOperationException("BREAKAWAY_NOT_DENIED");
}
if (mode is "immediate" or "multiple" or "grandchild" or "rapid" or "parent-exit")
{
    var required = mode == "multiple" ? 5 : 1;
    while (Directory.GetFiles(root, "child-*").Length < required) await Task.Delay(10, timeout.Token);
}
if (mode == "parent-exit") await target.WaitForExitAsync(timeout.Token);
if (mode is not "idle" and not "breakaway")
{
    var minimum = mode == "multiple" ? 6 : mode == "grandchild" ? 3 : mode == "parent-exit" ? 1 : 2;
    while (target.MemberPids().Count < minimum) await Task.Delay(10, timeout.Token);
}
var members = target.MemberPids().Select(pid =>
{ using var process = Process.GetProcessById(pid); return new { Pid = pid, Created = process.StartTime.ToUniversalTime().ToFileTimeUtc() }; }).ToArray();
var accounting = target.ProcessAccounting();
await Hold("family-running", new { members, total = accounting.Total, active = accounting.Active });
target.Abort(); Emit(new { stage = "quiesced", remaining = target.MemberPids().Count });
