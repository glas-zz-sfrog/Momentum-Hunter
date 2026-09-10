using System.Diagnostics;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;
using MomentumHunter.AutomationService;

namespace MomentumHunter.Integration.Tests;

public sealed class RetryLaunchGateTests
{
    private static string Python => Environment.GetEnvironmentVariable("MH_CONTAINMENT_TEST_PYTHON")
        ?? throw new InvalidOperationException("Bind MH_CONTAINMENT_TEST_PYTHON.");
    private static string Host => Environment.GetEnvironmentVariable("MH_CONTAINMENT_TEST_HOST")
        ?? throw new InvalidOperationException("Bind MH_CONTAINMENT_TEST_HOST to the exact built service executable.");
    private static RuntimeTopologyRule[] RuntimeRules => new[] { new RuntimeTopologyRule("CONSOLE_HOST",
        @"C:\Windows\System32\conhost.exe", Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(@"C:\Windows\System32\conhost.exe"))),
        @"\??\C:\WINDOWS\system32\conhost.exe 0x4", "PYTHON_TARGET", 1, 1) };

    private sealed class Fixture : IDisposable
    {
        public readonly string Root = Directory.CreateTempSubdirectory("MH-Prechild-Service-").FullName;
        public readonly RetryControllerSession Controller;
        public readonly Process Service;
        public readonly Task<string> Stdout;
        public readonly Task<string> Stderr;
        private readonly bool expectedContradiction;
        public Fixture(string? code = null, TimeSpan? duration = null, Action<string>? mutate = null, string? python = null,
            bool expectedContradiction = false)
        {
            this.expectedContradiction = expectedContradiction;
            Directory.CreateDirectory(Path.Combine(Root, "momentum_hunter"));
            File.WriteAllText(Path.Combine(Root, "momentum_hunter", "__init__.py"), "");
            File.WriteAllText(Path.Combine(Root, "momentum_hunter", "automation_supervisor.py"),
                code ?? "open('target-first.txt','x').write('first')\nimport time\nprint('fixture-ready',flush=True)\ntime.sleep(120)\n");
            var manifest = Path.Combine(Root, "manifest.json"); File.WriteAllText(manifest, "{}");
            python ??= Python;
            var info = new ProcessStartInfo(python) { WorkingDirectory = Root, UseShellExecute = false };
            foreach (var arg in new[] { "-B", "-m", "momentum_hunter.automation_supervisor", "run", "--manifest", manifest }) info.ArgumentList.Add(arg);
            var files = RetryLaunchGate.RequiredStaticFiles(info, Host).ToDictionary(Path.GetFullPath,
                    p => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(p))), StringComparer.OrdinalIgnoreCase);
            if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
            using var self = Process.GetCurrentProcess();
            Controller = new(Path.Combine(Root, "launch-contract.json"), info,
                WindowsIdentity.GetCurrent().User!.Value, self.SessionId, files, duration ?? TimeSpan.FromMinutes(2));
            mutate?.Invoke(Controller.ContractPath);
            var hostInfo = new ProcessStartInfo(Host) { UseShellExecute = false, CreateNoWindow = true,
                WorkingDirectory = Root, RedirectStandardOutput = true, RedirectStandardError = true };
            foreach (var arg in new[] { "--repository-root", Root, "--python-executable", python,
                "--manifest", manifest, "--launch-contract", Controller.ContractPath }) hostInfo.ArgumentList.Add(arg);
            Service = new Process { StartInfo = hostInfo };
            if (!Service.Start()) throw new InvalidOperationException("FIXTURE_HOST_NOT_STARTED");
            Stdout = Service.StandardOutput.ReadToEndAsync(); Stderr = Service.StandardError.ReadToEndAsync();
        }

        public async Task Admit()
        {
            using var bound = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            try
            {
                await Controller.AdmitAsync(ProcessTopologyIdentity.Capture(Service.Id,
                    Service.StartTime.ToUniversalTime().ToFileTimeUtc()), bound.Token);
            }
            catch (Exception failure)
            {
                Controller.Abort();
                await Service.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(10));
                throw new InvalidOperationException("PACKAGED_HOST_ADMISSION_FAILED: " + await Stdout + await Stderr, failure);
            }
        }

        public void Dispose()
        {
            try
            {
                if (expectedContradiction)
                {
                    Assert.True(Service.HasExited);
                    Assert.Empty(Controller.MemberPids());
                    Assert.Equal("CONTRADICTORY_RETRY_DECISION", Assert.Throws<InvalidOperationException>(() => Controller.Dispose()).Message);
                }
                else Controller.Dispose();
            }
            finally
            {
                if (!Service.HasExited) Service.Kill();
                if (!Service.WaitForExit(15000)) throw new TimeoutException("FIXTURE_HOST_SURVIVED");
                File.WriteAllText(Path.Combine(Root, "fixture-process-exit.json"), JsonSerializer.Serialize(new {
                    pid = Service.Id, createdAt = Service.StartTime.ToUniversalTime(), exitedAt = Service.ExitTime.ToUniversalTime(),
                    stdoutCompleted = Stdout.IsCompleted, stderrCompleted = Stderr.IsCompleted }));
                File.WriteAllText(Path.Combine(Root, "fixture-host-stdout.txt"), Stdout.IsCompletedSuccessfully ? Stdout.Result : "TRANSCRIPT_DRAIN_NOT_COMPLETED");
                File.WriteAllText(Path.Combine(Root, "fixture-host-stderr.txt"), Stderr.IsCompletedSuccessfully ? Stderr.Result : "TRANSCRIPT_DRAIN_NOT_COMPLETED");
                Service.Dispose();
            }
        }
    }

    [Fact]
    public async Task ExactBuiltHostHandshakeTargetAndAbortAreContained()
    {
        using var fixture = new Fixture();
        Assert.False(File.Exists(Path.Combine(fixture.Root, "target-first.txt")));
        await fixture.Admit();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await fixture.Controller.CheckAsync(RuntimeRules, timeout.Token);
        Assert.Contains(fixture.Service.Id, fixture.Controller.MemberPids());
        Assert.Contains(fixture.Controller.Target.TargetPid, fixture.Controller.MemberPids());
        fixture.Controller.Abort();
        Assert.Empty(fixture.Controller.MemberPids());
        await fixture.Service.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
    }

    [Fact]
    public async Task PermanentHandoffSurvivesControllerCloseButNotLauncherDeath()
    {
        using var fixture = new Fixture();
        await fixture.Admit();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await fixture.Controller.CheckAsync(RuntimeRules, timeout.Token);
        await fixture.Controller.CommitPermanentAsync(timeout.Token);
        Assert.True(fixture.Controller.ReconcileCommit());
        var target = fixture.Controller.Target;
        using var process = Process.GetProcessById(target.TargetPid);
        Assert.Equal(target.TargetCreatedFileTime, process.StartTime.ToUniversalTime().ToFileTimeUtc());
        fixture.Controller.Dispose();
        Assert.False(fixture.Service.HasExited);
        Assert.False(process.HasExited);
        fixture.Service.Kill();
        await fixture.Service.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
        await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
    }

    [Theory]
    [InlineData("malformed")]
    [InlineData("duplicate")]
    [InlineData("wrong-python")]
    [InlineData("wrong-args")]
    [InlineData("wrong-sid")]
    [InlineData("wrong-session")]
    [InlineData("expired")]
    [InlineData("wrong-controller-birth")]
    [InlineData("wrong-pipe")]
    [InlineData("missing-static")]
    [InlineData("missing-nested-static")]
    [InlineData("tampered-static")]
    [InlineData("torn-permanent")]
    [InlineData("partial-permanent")]
    public async Task InvalidPersistentContractNeverStartsPython(string mutation)
    {
        using var fixture = new Fixture(expectedContradiction: mutation == "torn-permanent", mutate: path =>
        {
            var value = RetryLaunchGate.Decode<RuntimeLaunchContract>(File.ReadAllBytes(path));
            switch (mutation)
            {
                case "malformed": File.WriteAllText(path, "{"); return;
                case "duplicate": File.WriteAllText(path, "{\"SchemaVersion\":1," + File.ReadAllText(path)[1..]); return;
                case "wrong-python": value = value with { Executable = @"C:\foreign\python.exe" }; break;
                case "wrong-args": value = value with { Arguments = new[] { "--foreign" } }; break;
                case "wrong-sid": value = value with { ServiceUserSid = "S-1-0-0" }; break;
                case "wrong-session": value = value with { ServiceSessionId = value.ServiceSessionId + 1 }; break;
                case "expired": value = value with { DeadlineUtc = DateTimeOffset.UtcNow.AddSeconds(-1) }; break;
                case "wrong-controller-birth": value = value with { Controller = value.Controller with { CreatedFileTime = value.Controller.CreatedFileTime - 1 } }; break;
                case "wrong-pipe": value = value with { PipeName = "FOREIGN" }; break;
                case "missing-static": value.StaticFiles.Clear(); break;
                case "missing-nested-static":
                    var nested = value.StaticFiles.Keys.Single(key => key.EndsWith(
                        @"runtimes\win\lib\net8.0\System.Diagnostics.EventLog.dll", StringComparison.OrdinalIgnoreCase));
                    value.StaticFiles.Remove(nested); break;
                case "tampered-static": value.StaticFiles[value.Executable] = new string('0',64); break;
                case "torn-permanent": File.WriteAllText(path + ".permanent.json", "{"); break;
                case "partial-permanent": File.WriteAllText(path + ".permanent.json.partial-test", "{}"); break;
            }
            File.WriteAllBytes(path, JsonSerializer.SerializeToUtf8Bytes(value, RetryLaunchGate.JsonOptions));
        });
        var deadline = DateTime.UtcNow.AddSeconds(20);
        try { await fixture.Service.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(20)); }
        catch (TimeoutException)
        {
            // A delayed managed exit notification is not a live-process finding. Accept
            // only independent kernel exit evidence strictly within the original deadline.
            if (!fixture.Service.HasExited || fixture.Service.ExitTime.ToUniversalTime() > deadline)
                throw new TimeoutException("HOST_REJECTION_EXIT_NOT_PROVEN_WITHIN_ORIGINAL_20_SECOND_DEADLINE");
        }
        File.WriteAllText(Path.Combine(fixture.Root, "invalid-contract-exit-proof.json"), JsonSerializer.Serialize(new {
            mutation, deadline, kernelExitAt = fixture.Service.ExitTime.ToUniversalTime(), markerPresent = File.Exists(Path.Combine(fixture.Root, "target-first.txt")) }));
        Assert.False(File.Exists(Path.Combine(fixture.Root, "target-first.txt")));
        Assert.Empty(fixture.Controller.MemberPids());
        if (mutation == "missing-nested-static")
            Assert.Contains("LAUNCH_STATIC_CLOSURE_INCOMPLETE", await fixture.Stdout + await fixture.Stderr);
    }

    [Theory]
    [InlineData("operator-abort")]
    [InlineData("readiness-failure")]
    [InlineData("controller-exception")]
    [InlineData("topology-failure")]
    [InlineData("target-death")]
    public async Task FailureRevokesServiceAndLiveDescendants(string failure)
    {
        using var fixture = new Fixture("open('target-first.txt','x').write('first')\nimport subprocess,sys,time\nsubprocess.Popen([sys.executable,'-B','-c',\"open('child-first.txt','x').write('child');import time;time.sleep(120)\"],creationflags=8)\ntime.sleep(120)\n");
        await fixture.Admit();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        while (!File.Exists(Path.Combine(fixture.Root, "child-first.txt"))) await Task.Delay(10, timeout.Token);
        var ids = fixture.Controller.MemberPids();
        Assert.True(ids.Count >= 3);
        if (failure == "topology-failure")
            Assert.Throws<InvalidOperationException>(() => fixture.Controller.ValidateRunningTopology(RuntimeRules));
        if (failure == "target-death")
        {
            var identity = fixture.Controller.Target;
            using var process = Process.GetProcessById(identity.TargetPid);
            _ = process.SafeHandle;
            Assert.Equal(identity.TargetCreatedFileTime, process.StartTime.ToUniversalTime().ToFileTimeUtc());
            process.Kill();
            await fixture.Service.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
        }
        else fixture.Controller.Abort();
        Assert.Empty(fixture.Controller.MemberPids());
        Assert.False(File.Exists(fixture.Controller.ContractPath + ".permanent.json"));
    }

    [Fact]
    public async Task ReadinessSilenceDeadlineKillsFamilyWithoutCommit()
    {
        using var fixture = new Fixture(duration: TimeSpan.FromSeconds(8));
        await fixture.Admit();
        await fixture.Service.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
        Assert.Empty(fixture.Controller.MemberPids());
        Assert.False(File.Exists(fixture.Controller.ContractPath + ".permanent.json"));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task ConfiguredVenvRedirectorIsContainedAndExactlyIdentified(bool forwardSlashes)
    {
        var venv = Environment.GetEnvironmentVariable("MH_CONTAINMENT_TEST_VENV")
            ?? throw new InvalidOperationException("Bind exact configured venv.");
        if (forwardSlashes) venv = venv.Replace('\\', '/');
        using var fixture = new Fixture(python: venv);
        await fixture.Admit();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        while (!File.Exists(Path.Combine(fixture.Root, "target-first.txt"))) await Task.Delay(10, timeout.Token);
        var observed = fixture.Controller.MemberPids().Select(pid =>
        { using var process = Process.GetProcessById(pid); return ProcessTopologyIdentity.Capture(pid, process.StartTime.ToUniversalTime().ToFileTimeUtc()); }).ToArray();
        File.WriteAllText(Path.Combine(fixture.Root, "venv-topology.json"), JsonSerializer.Serialize(observed));
        Assert.Equal(Path.GetFullPath(venv), fixture.Controller.Target.Executable, ignoreCase: true);
        Assert.Contains(observed, p => p.Executable.Equals(Python, StringComparison.OrdinalIgnoreCase)
            && p.ParentPid == fixture.Controller.Target.TargetPid);
        var baseProcess = Assert.Single(observed, p => p.Executable.Equals(Python, StringComparison.OrdinalIgnoreCase));
        var rules = RuntimeRules.Concat(new[] {new RuntimeTopologyRule("BASE_PYTHON", Python,
            baseProcess.ExecutableSha256, baseProcess.CommandLine, "PYTHON_TARGET", 1, 1)}).ToArray();
        await fixture.Controller.CheckAsync(rules, timeout.Token);
        Assert.Throws<InvalidOperationException>(() => fixture.Controller.ValidateRunningTopology(
            RuntimeRules.Concat(new[] {rules[1] with {CommandLine = "wrong arguments"}}).ToArray()));
        fixture.Controller.Abort();
        Assert.Empty(fixture.Controller.MemberPids());
    }

    [Fact]
    public async Task SpawnDuringTopologyValidationFailsClosedAndQuiesces()
    {
        using var fixture = new Fixture("open('target-first.txt','x').write('first')\nimport subprocess,sys,time\nwhile True:\n p=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(.1)'],creationflags=8)\n open('spawning.txt','w').write(str(p.pid))\n p.wait()\n");
        await fixture.Admit();
        using var bound = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        while (!File.Exists(Path.Combine(fixture.Root, "spawning.txt"))) await Task.Delay(10, bound.Token);
        await Assert.ThrowsAnyAsync<Exception>(() => fixture.Controller.CheckAsync(RuntimeRules, bound.Token));
        fixture.Controller.Abort();
        Assert.Empty(fixture.Controller.MemberPids());
    }

    [Fact]
    public async Task AcceptedPersistentSelectorRestartsFreshContainedFamilyWithoutOldController()
    {
        using var fixture = new Fixture("import os,time\nwith open('incarnations.txt','a') as f:f.write(str(os.getpid())+'\\n');f.flush()\ntime.sleep(120)\n");
        await fixture.Admit();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        await fixture.Controller.CheckAsync(RuntimeRules, timeout.Token);
        await fixture.Controller.CommitPermanentAsync(timeout.Token);
        var first = fixture.Controller.Target;
        using var firstProcess = Process.GetProcessById(first.TargetPid);
        _ = firstProcess.SafeHandle;
        Assert.Equal(first.TargetCreatedFileTime, firstProcess.StartTime.ToUniversalTime().ToFileTimeUtc());
        fixture.Controller.Dispose();
        fixture.Service.Kill();
        await fixture.Service.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
        await firstProcess.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
        using var restarted = Process.Start(fixture.Service.StartInfo)!;
        _ = restarted.SafeHandle;
        var stdout = restarted.StandardOutput.ReadToEndAsync(); var stderr = restarted.StandardError.ReadToEndAsync();
        Process? secondProcess = null;
        try
        {
            string[] rows;
            do {
                timeout.Token.ThrowIfCancellationRequested();
                rows = File.ReadAllLines(Path.Combine(fixture.Root, "incarnations.txt"));
                if (rows.Length < 2) await Task.Delay(10, timeout.Token);
            } while (rows.Length < 2);
            var pid = int.Parse(rows[1]);
            secondProcess = Process.GetProcessById(pid); _ = secondProcess.SafeHandle;
            var identity = ProcessTopologyIdentity.Capture(pid, secondProcess.StartTime.ToUniversalTime().ToFileTimeUtc());
            Assert.Equal(restarted.Id, identity.ParentPid);
            Assert.Equal(Python, identity.Executable, ignoreCase: true);
            Assert.True(identity.CreatedFileTime >= restarted.StartTime.ToUniversalTime().ToFileTimeUtc());
            Assert.NotEqual(first.TargetCreatedFileTime, identity.CreatedFileTime);
            restarted.Kill();
            await restarted.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
            await secondProcess.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
        }
        finally
        {
            if (!restarted.HasExited) restarted.Kill();
            await restarted.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
            // Only an identity-proven fixture member is retained above; host Job owns cleanup.
            secondProcess?.Dispose();
            File.WriteAllText(Path.Combine(fixture.Root, "permanent-restart-stdout.txt"), await stdout);
            File.WriteAllText(Path.Combine(fixture.Root, "permanent-restart-stderr.txt"), await stderr);
        }
    }
}
