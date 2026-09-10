using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace MomentumHunter.AutomationService;

public sealed record ControllerIdentity(int Pid, long CreatedFileTime, string Executable,
    string ExecutableSha256, string UserSid, int SessionId, long JobHandle, string AttemptId);

/// <summary>The retry controller's sole outer-Job ownership. Never inherited by targets.</summary>
public sealed class ControllerJobCustody : IDisposable
{
    private readonly KernelHandle job;
    public ControllerIdentity Identity { get; }
    public ControllerJobCustody()
    {
        job = Native.CreateJobObjectW(IntPtr.Zero, null);
        Native.Require(!job.IsInvalid, "CREATE_CONTROLLER_JOB");
        try
        {
            var limits = new Native.ExtendedLimits(); limits.Basic.LimitFlags = 0x2000;
            Native.Require(Native.SetInformationJobObject(job, 9, ref limits,
                (uint)Marshal.SizeOf<Native.ExtendedLimits>()), "CONFIGURE_CONTROLLER_JOB");
            using var self = Native.OpenProcess(0x1000 | 0x100000, false, Environment.ProcessId);
            var identity = WindowsContainedProcess.ReadIdentity(self);
            Identity = new(identity.Pid, identity.Created, identity.Path,
                Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(identity.Path))),
                identity.Sid, identity.Session, job.DangerousGetHandle().ToInt64(), Guid.NewGuid().ToString("N"));
        }
        catch { job.Dispose(); throw; }
    }
    public void Abort() => Native.Require(Native.TerminateJobObject(job, 125), "ABORT_CONTROLLER_JOB");
    public IReadOnlyList<int> MemberPids() => Native.ReadJobPids(job);
    public ProcessTopologyIdentity InspectMember(int pid)
    {
        using var handle = Native.OpenProcess(0x1000 | 0x100000, false, pid);
        Native.Require(!handle.IsInvalid, "OPEN_EXACT_JOB_MEMBER");
        Native.Require(Native.IsProcessInJob(handle, job, out var member) && member, "MEMBER_OBJECT_NOT_IN_JOB");
        var identity = ProcessTopologyIdentity.Capture(handle);
        if (Native.WaitForSingleObject(handle, 0) != 258) throw new InvalidOperationException("JOB_MEMBER_EXITED");
        return identity;
    }
    public void EnrollLauncher(ProcessTopologyIdentity expected)
    {
        if (expected.Pid == Environment.ProcessId) throw new InvalidOperationException("CONTROLLER_NOT_A_LAUNCHER");
        using var process = Native.OpenProcess(0x1000 | 0x100000 | 0x100 | 1, false, expected.Pid);
        Native.Require(!process.IsInvalid, "OPEN_EXACT_LAUNCHER");
        if (ProcessTopologyIdentity.Capture(process) != expected)
            throw new InvalidOperationException("LAUNCHER_CHANGED_BEFORE_ENROLLMENT");
        Native.Require(AssignProcessToJobObject(job, process), "ENROLL_WAITING_LAUNCHER");
        Native.Require(Native.IsProcessInJob(process, job, out var member) && member, "VERIFY_LAUNCHER_JOB");
    }
    public void Dispose() => job.Dispose();
    [DllImport("kernel32", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(KernelHandle job, KernelHandle process);
}

/// <summary>Retained controller identity; actual service borrows the Job only after durable handoff.</summary>
public sealed class ControllerProcessLease : IDisposable
{
    private readonly KernelHandle process;
    public ControllerIdentity Identity { get; }
    public ControllerProcessLease(ControllerIdentity expected)
    {
        if (expected.Pid <= 0 || expected.CreatedFileTime <= 0 || expected.JobHandle <= 0
            || !Guid.TryParseExact(expected.AttemptId, "N", out _))
            throw new ArgumentException("INVALID_CONTROLLER_IDENTITY");
        process = Native.OpenProcess(0x1000 | 0x100000 | 0x0040, false, expected.Pid);
        try
        {
            Native.Require(!process.IsInvalid, "OPEN_EXACT_CONTROLLER");
            var actual = WindowsContainedProcess.ReadIdentity(process);
            if (actual.Pid != expected.Pid || actual.Created != expected.CreatedFileTime
                || !WindowsContainedProcess.SamePath(actual.Path, expected.Executable)
                || actual.Sid != expected.UserSid || actual.Session != expected.SessionId
                || Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(actual.Path))) != expected.ExecutableSha256)
                throw new InvalidOperationException("CONTROLLER_IDENTITY_MISMATCH");
            Identity = expected;
            RequireAlive();
        }
        catch { process.Dispose(); throw; }
    }

    public void RequireAlive()
    {
        var result = Native.WaitForSingleObject(process, 0);
        if (result != 258) throw new InvalidOperationException("CONTROLLER_NOT_ALIVE");
    }

    internal KernelHandle BorrowJob()
    {
        RequireAlive();
        Native.Require(Native.DuplicateHandle(process, new IntPtr(Identity.JobHandle),
            Native.GetCurrentProcess(), out var job, 0, false, 2), "BORROW_CONTROLLER_JOB");
        try
        {
            var memory = Marshal.AllocHGlobal(Marshal.SizeOf<Native.ExtendedLimits>());
            try
            {
                Native.Require(Native.QueryInformationJobObject(job, 9, memory,
                    (uint)Marshal.SizeOf<Native.ExtendedLimits>(), out _), "VERIFY_CONTROLLER_JOB_POLICY");
                var limits = Marshal.PtrToStructure<Native.ExtendedLimits>(memory);
                if (limits.Basic.LimitFlags != 0x2000)
                    throw new InvalidOperationException("CONTROLLER_JOB_POLICY_MISMATCH");
            }
            finally { Marshal.FreeHGlobal(memory); }
            RequireAlive();
            return job;
        }
        catch { job.Dispose(); throw; }
    }

    public void Dispose() => process.Dispose();
}
