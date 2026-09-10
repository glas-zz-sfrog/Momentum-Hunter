using System.Diagnostics;
using System.Runtime.InteropServices;
using MomentumHunter.AutomationService;

namespace MomentumHunter.Integration.Tests;

public sealed class PrechildContainmentTests
{
    private static string Python => Environment.GetEnvironmentVariable("MH_CONTAINMENT_TEST_PYTHON")
        ?? throw new InvalidOperationException("MH_CONTAINMENT_TEST_PYTHON must bind the approved interpreter for Windows physical tests.");

    private static ProcessStartInfo Target(string root, string code)
    {
        var info = new ProcessStartInfo(Python) { WorkingDirectory = root, UseShellExecute = false };
        info.ArgumentList.Add("-B"); info.ArgumentList.Add("-c"); info.ArgumentList.Add(code);
        info.Environment.Remove("OPENAI_API_KEY"); info.Environment.Remove("CODEX_API_KEY");
        return info;
    }

    [Fact]
    public async Task FirstUserActionOnlyAfterVerifiedResume()
    {
        var root = Directory.CreateTempSubdirectory("MH-Prechild-First-").FullName;
        var marker = Path.Combine(root, "first.txt");
        using var target = WindowsContainedProcess.CreateSuspended(Target(root,
            "open('first.txt','x').write('first'); import time; time.sleep(60)"));
        Assert.True(target.Identity.ContainmentConfirmed);
        Assert.False(target.Resumed);
        Assert.False(File.Exists(marker));
        Assert.Contains(target.Identity.TargetPid, target.MemberPids());
        // An actual observation interval confirms suspended code cannot produce its first marker.
        await Task.Delay(100);
        Assert.False(File.Exists(marker));
        var verifiedAt = DateTimeOffset.UtcNow;
        target.Resume();
        await Until(() => File.Exists(marker));
        var observedAt = DateTimeOffset.UtcNow;
        target.Abort();
        Assert.Empty(target.MemberPids());
        File.WriteAllText(Path.Combine(root, "first-action-proof.json"), System.Text.Json.JsonSerializer.Serialize(new {
            identity = target.Identity, verifiedContainedWhileMarkerAbsentAt = verifiedAt,
            firstMarkerObservedAt = observedAt, markerPresentBeforeResume = false,
            markerPresentAfterResume = true, survivingTaskProcessCount = target.MemberPids().Count }));
    }

    [Theory]
    [InlineData(LaunchStage.BeforeJob)]
    [InlineData(LaunchStage.JobConfigured)]
    [InlineData(LaunchStage.BeforeCreate)]
    [InlineData(LaunchStage.CreatedSuspended)]
    [InlineData(LaunchStage.Verified)]
    public void FailureBeforeResumeNeverExecutesTarget(LaunchStage stage)
    {
        var root = Directory.CreateTempSubdirectory("MH-Prechild-Failure-").FullName;
        Assert.Throws<InjectedFailure>(() => WindowsContainedProcess.CreateSuspended(Target(root,
            "from pathlib import Path; Path('forbidden.txt').write_text('bad')"),
            current => { if (current == stage) throw new InjectedFailure(); }));
        Assert.False(File.Exists(Path.Combine(root, "forbidden.txt")));
    }

    [Theory]
    [InlineData(LaunchStage.BeforeResume)]
    [InlineData(LaunchStage.Resumed)]
    public void ResumeStageFailureRevokesWholeJob(LaunchStage stage)
    {
        var root = Directory.CreateTempSubdirectory("MH-Prechild-Resume-").FullName;
        using var target = WindowsContainedProcess.CreateSuspended(Target(root,
            "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); time.sleep(60)"));
        Assert.Throws<InjectedFailure>(() => target.Resume(current => { if (current == stage) throw new InjectedFailure(); }));
        Assert.Empty(target.MemberPids());
    }

    [Fact]
    public async Task ImmediateDetachedGrandchildInheritedAndRevokedAfterParentExit()
    {
        var root = Directory.CreateTempSubdirectory("MH-Prechild-Family-").FullName;
        var child = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],creationflags=8); time.sleep(60)";
        var code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c'," + System.Text.Json.JsonSerializer.Serialize(child) + "]); print('spawned',flush=True)";
        using var target = WindowsContainedProcess.CreateSuspended(Target(root, code));
        target.Resume();
        await target.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
        await Until(() => target.MemberPids().Count >= 2);
        target.Abort();
        Assert.Empty(target.MemberPids());
    }

    [Fact]
    public async Task BreakawayIsRejectedByKernel()
    {
        var root = Directory.CreateTempSubdirectory("MH-Prechild-Breakaway-").FullName;
        var code = "import subprocess,sys\ntry:\n subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],creationflags=0x01000000)\nexcept OSError as e:\n print(e.winerror,flush=True)\nelse:\n raise Exception('BREAKAWAY_ACCEPTED')";
        using var target = WindowsContainedProcess.CreateSuspended(Target(root, code));
        target.Resume();
        await target.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
        Assert.Equal(0u, target.ExitCode);
        Assert.Equal("5", (await target.StandardOutput.ReadToEndAsync()).Trim());
        Assert.Empty(target.MemberPids());
    }

    private static async Task Until(Func<bool> condition)
    {
        var watch = Stopwatch.StartNew();
        while (!condition())
        {
            if (watch.Elapsed > TimeSpan.FromSeconds(15)) throw new TimeoutException("PHYSICAL_OBSERVATION_TIMEOUT");
            await Task.Delay(10);
        }
    }
    private sealed class InjectedFailure : Exception { }

    [Fact]
    public async Task KernelAssignmentFailureNeverExecutesFirstAction()
    {
        var root = Directory.CreateTempSubdirectory("MH-Prechild-Assignment-").FullName;
        using var owner = new ControllerJobCustody();
        using var lease = new ControllerProcessLease(owner.Identity);
        using var placeholder = Process.Start(Target(root, "import time;time.sleep(120)"))!;
        _ = placeholder.SafeHandle;
        try
        {
            owner.EnrollLauncher(ProcessTopologyIdentity.Capture(placeholder.Id,
                placeholder.StartTime.ToUniversalTime().ToFileTimeUtc()));
            Assert.Throws<System.ComponentModel.Win32Exception>(() =>
            {
                using var target = WindowsContainedProcess.CreateSuspended(Target(root,
                    "open('forbidden.txt','x').write('bad')"), observe: stage =>
                    {
                        if (stage != LaunchStage.BeforeCreate) return;
                        // Fault injection only: exhaust this disposable outer Job immediately
                        // before the canonical atomic JOB_LIST CreateProcess call.
                        var limits = new ExtendedLimits();
                        limits.Basic.Flags = 0x2008;
                        limits.Basic.Active = 1;
                        if (!SetInformationJobObject(new IntPtr(owner.Identity.JobHandle), 9,
                            ref limits, (uint)Marshal.SizeOf<ExtendedLimits>()))
                            throw new InvalidOperationException("ASSIGNMENT_FAILURE_FIXTURE_CONFIGURATION");
                    }, controller: lease);
                target.Resume();
            });
            Assert.False(File.Exists(Path.Combine(root, "forbidden.txt")));
            Assert.Equal(new[] {placeholder.Id}, owner.MemberPids());
        }
        finally
        {
            owner.Abort();
            if (!placeholder.HasExited) placeholder.Kill();
            await placeholder.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
        }
        Assert.Empty(owner.MemberPids());
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct BasicLimits { public long ProcessTime, JobTime; public uint Flags; public UIntPtr Minimum, Maximum;
        public uint Active; public UIntPtr Affinity; public uint Priority, Scheduling; }
    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters { public ulong Read, Write, Other, ReadBytes, WriteBytes, OtherBytes; }
    [StructLayout(LayoutKind.Sequential)]
    private struct ExtendedLimits { public BasicLimits Basic; public IoCounters Io; public UIntPtr ProcessMemory, JobMemory, PeakProcess, PeakJob; }
    [DllImport("kernel32", SetLastError = true)]
    private static extern bool SetInformationJobObject(IntPtr job, int type, ref ExtendedLimits value, uint size);

    [Fact]
    public async Task SpawnDuringAbortCannotOutliveJobAndDoesNotKillUnrelatedSameExecutable()
    {
        var root = Directory.CreateTempSubdirectory("MH-Prechild-Concurrent-Abort-").FullName;
        using var unrelated = WindowsContainedProcess.CreateSuspended(Target(root, "import time;time.sleep(120)"));
        unrelated.Resume();
        var code = "import subprocess,sys,time\nfor i in range(200):\n p=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(.05)'],creationflags=8)\n open('spawning.txt','w').write(str(i))\n p.wait()\n";
        using var target = WindowsContainedProcess.CreateSuspended(Target(root, code));
        target.Resume();
        await Until(() => File.Exists(Path.Combine(root, "spawning.txt")) && target.ProcessAccounting().Total >= 3);
        Assert.Throws<InvalidOperationException>(() => target.InspectMember(unrelated.Identity.TargetPid));
        target.Abort();
        Assert.Empty(target.MemberPids());
        Assert.Equal(0u, target.ProcessAccounting().Active);
        Assert.Equal(259u, unrelated.ExitCode);
        Assert.Contains(unrelated.Identity.TargetPid, unrelated.MemberPids());
    }

    [Fact]
    public async Task ControllerLastHandleClosureKillsFamilyWithoutHostCooperation()
    {
        var root = Directory.CreateTempSubdirectory("MH-Prechild-Outer-").FullName;
        using var owner = new ControllerJobCustody();
        using var lease = new ControllerProcessLease(owner.Identity);
        using var target = WindowsContainedProcess.CreateSuspended(Target(root,
            "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); time.sleep(60)"), controller: lease);
        target.Resume();
        await Until(() => target.MemberPids().Count >= 2);
        owner.Dispose();
        await target.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
        await Until(() => target.MemberPids().Count == 0);
    }

    [Fact]
    public void ControllerPidReuseAndImpersonationCannotBind()
    {
        using var owner = new ControllerJobCustody();
        var identity = owner.Identity;
        Assert.Throws<InvalidOperationException>(() => new ControllerProcessLease(identity with { CreatedFileTime = identity.CreatedFileTime - 1 }));
        Assert.Throws<InvalidOperationException>(() => new ControllerProcessLease(identity with { Executable = @"C:\foreign\python.exe" }));
        Assert.Throws<InvalidOperationException>(() => new ControllerProcessLease(identity with { UserSid = "S-1-0-0" }));
        Assert.Throws<InvalidOperationException>(() => new ControllerProcessLease(identity with { SessionId = identity.SessionId + 1 }));
        Assert.Throws<InvalidOperationException>(() => new ControllerProcessLease(identity with { ExecutableSha256 = new string('0', 64) }));
    }

    [Fact]
    public void SuspendedTopologyChecksNativeIdentityParentArgumentsAndPopulation()
    {
        var root = Directory.CreateTempSubdirectory("MH-Prechild-Topology-").FullName;
        using var target = WindowsContainedProcess.CreateSuspended(Target(root, "import time;time.sleep(60)"));
        var expected = target.Identity;
        var actual = target.InspectMember(expected.TargetPid);
        var members = target.MemberPids();
        ProcessTopologyIdentity.ValidateSuspended(expected, actual, members);
        var wrong = new[] { actual with { Pid = actual.Pid + 1 }, actual with { ParentPid = actual.ParentPid + 1 },
            actual with { CreatedFileTime = actual.CreatedFileTime - 1 },
            actual with { Executable = @"C:\foreign\python.exe" }, actual with { ExecutableSha256 = new string('0',64) },
            actual with { CommandLine = actual.CommandLine + " --foreign" }, actual with { UserSid = "S-1-0-0" },
            actual with { SessionId = actual.SessionId + 1 } };
        foreach (var mutation in wrong)
            Assert.Throws<InvalidOperationException>(() => ProcessTopologyIdentity.ValidateSuspended(expected, mutation, members));
        Assert.Throws<InvalidOperationException>(() => ProcessTopologyIdentity.ValidateSuspended(expected, actual, new[] { actual.Pid, actual.Pid + 1 }));
        Assert.Throws<InvalidOperationException>(() => target.InspectMember(Environment.ProcessId));
        Assert.Throws<InvalidOperationException>(() => ProcessTopologyIdentity.Capture(actual.Pid, actual.CreatedFileTime - 1));
    }
}
