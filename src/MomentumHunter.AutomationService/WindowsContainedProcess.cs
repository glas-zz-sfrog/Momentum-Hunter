using System.ComponentModel;
using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace MomentumHunter.AutomationService;

public enum LaunchStage { BeforeJob, JobConfigured, BeforeCreate, CreatedSuspended, Verified, BeforeResume, Resumed }

public sealed record ContainedIdentity(
    int LauncherPid, long LauncherCreatedFileTime, int TargetPid,
    long TargetCreatedFileTime, string Executable, string ExecutableSha256,
    string CommandLine, string WorkingDirectory, string UserSid, int SessionId,
    string ContainmentId, bool ContainmentConfirmed);

/// <summary>Creator-owned, unnamed Job custody. Never discovers a process to kill by name.</summary>
public sealed class WindowsContainedProcess : IDisposable
{
    private readonly object gate = new();
    private readonly KernelHandle job;
    private readonly KernelHandle target;
    private readonly KernelHandle thread;
    private readonly FileStream imageLock;
    private bool disposed;
    private bool resumed;
    public ContainedIdentity Identity { get; }
    public StreamReader StandardOutput { get; }
    public StreamReader StandardError { get; }
    public bool Resumed { get { lock (gate) return resumed; } }

    private WindowsContainedProcess(KernelHandle job, Native.ProcessInformation pi,
        FileStream imageLock, AnonymousPipeServerStream stdout,
        AnonymousPipeServerStream stderr, ContainedIdentity identity)
    {
        this.job = job;
        target = new KernelHandle(pi.Process);
        thread = new KernelHandle(pi.Thread);
        this.imageLock = imageLock;
        StandardOutput = new StreamReader(stdout, Encoding.UTF8);
        StandardError = new StreamReader(stderr, Encoding.UTF8);
        Identity = identity;
    }

    public static WindowsContainedProcess CreateSuspended(ProcessStartInfo info,
        Action<LaunchStage>? observe = null, ControllerProcessLease? controller = null)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        if (!Path.IsPathFullyQualified(info.FileName) || !File.Exists(info.FileName)
            || !Path.IsPathFullyQualified(info.WorkingDirectory)
            || !Directory.Exists(info.WorkingDirectory) || info.UseShellExecute
            || !string.IsNullOrEmpty(info.Arguments))
            throw new ArgumentException("EXACT_ABSOLUTE_LAUNCH_SPEC_REQUIRED");
        observe?.Invoke(LaunchStage.BeforeJob);
        KernelHandle? job = null;
        FileStream? image = null;
        AnonymousPipeServerStream? stdout = null, stderr = null;
        WindowsContainedProcess? result = null;
        Native.ProcessInformation pi = default;
        KernelHandle? outerJob = null;
        try
        {
            job = Native.CreateJobObjectW(IntPtr.Zero, null);
            Native.Require(!job.IsInvalid, "CREATE_JOB");
            var limits = new Native.ExtendedLimits();
            limits.Basic.LimitFlags = 0x2000; // KILL_ON_JOB_CLOSE; no breakaway permission.
            Native.Require(Native.SetInformationJobObject(job, 9, ref limits,
                (uint)Marshal.SizeOf<Native.ExtendedLimits>()), "CONFIGURE_JOB");
            observe?.Invoke(LaunchStage.JobConfigured);
            outerJob = controller?.BorrowJob();
            image = new FileStream(info.FileName, FileMode.Open, FileAccess.Read, FileShare.Read);
            stdout = new AnonymousPipeServerStream(PipeDirection.In, HandleInheritability.Inheritable);
            stderr = new AnonymousPipeServerStream(PipeDirection.In, HandleInheritability.Inheritable);
            var sa = new Native.SecurityAttributes { Length = Marshal.SizeOf<Native.SecurityAttributes>(), Inherit = true };
            using var stdin = Native.CreateFileW("NUL", 0x80000000, 3, ref sa, 3, 0, IntPtr.Zero);
            Native.Require(!stdin.IsInvalid, "OPEN_NULL_STDIN");
            using var attributes = new Native.Attributes(outerJob is null
                ? new[] { job.DangerousGetHandle() }
                : new[] { outerJob.DangerousGetHandle(), job.DangerousGetHandle() }, new[] {
                stdin.DangerousGetHandle(), stdout.ClientSafePipeHandle.DangerousGetHandle(),
                stderr.ClientSafePipeHandle.DangerousGetHandle() });
            var startup = new Native.StartupInfoEx();
            startup.Startup.Size = Marshal.SizeOf<Native.StartupInfoEx>();
            startup.Startup.Flags = 0x100; // STARTF_USESTDHANDLES, explicit HANDLE_LIST only.
            startup.Startup.Input = stdin.DangerousGetHandle();
            startup.Startup.Output = stdout.ClientSafePipeHandle.DangerousGetHandle();
            startup.Startup.Error = stderr.ClientSafePipeHandle.DangerousGetHandle();
            startup.Attributes = attributes.List;
            var commandLine = string.Join(" ", new[] { info.FileName }.Concat(info.ArgumentList).Select(Quote));
            var environment = string.Join('\0', info.Environment.OrderBy(x => x.Key, StringComparer.OrdinalIgnoreCase)
                .Select(x => EnvironmentEntry(x.Key, x.Value))) + "\0\0";
            observe?.Invoke(LaunchStage.BeforeCreate);
            // JOB_LIST makes association atomic with creation, including creator death before return.
            Native.Require(Native.CreateProcessW(info.FileName, new StringBuilder(commandLine),
                IntPtr.Zero, IntPtr.Zero, true, 0x00080000 | 0x00000400 | 0x08000000 | 0x00000004,
                environment, info.WorkingDirectory, ref startup, out pi), "CREATE_CONTAINED_SUSPENDED");
            stdout.DisposeLocalCopyOfClientHandle();
            stderr.DisposeLocalCopyOfClientHandle();
            observe?.Invoke(LaunchStage.CreatedSuspended);
            ContainedIdentity identity;
            using (var borrowed = new KernelHandle(pi.Process, false))
            using (var creator = Process.GetCurrentProcess())
            {
                var actual = ReadIdentity(borrowed);
                if (actual.Pid != pi.ProcessId || !SamePath(actual.Path, info.FileName))
                    throw new InvalidOperationException("CREATED_TARGET_IDENTITY_MISMATCH");
                if (!IsMember(borrowed, job)) throw new InvalidOperationException("CONTAINMENT_NOT_CONFIRMED");
                if (outerJob is not null && !IsMember(borrowed, outerJob))
                    throw new InvalidOperationException("CONTROLLER_CONTAINMENT_NOT_CONFIRMED");
                identity = new(creator.Id, creator.StartTime.ToUniversalTime().ToFileTimeUtc(),
                    actual.Pid, actual.Created, actual.Path, Convert.ToHexString(SHA256.HashData(image)),
                    commandLine, Path.GetFullPath(info.WorkingDirectory), actual.Sid, actual.Session,
                    Guid.NewGuid().ToString("N"), true);
            }
            result = new(job, pi, image, stdout, stderr, identity);
            pi = default;
            job = null; image = null; stdout = null; stderr = null;
            observe?.Invoke(LaunchStage.Verified);
            return result;
        }
        catch
        {
            if (result is not null) result.Dispose();
            else if (job is not null && !job.IsInvalid) Native.TerminateJobObject(job, 125);
            throw;
        }
        finally
        {
            if (pi.Thread != IntPtr.Zero) Native.CloseHandle(pi.Thread);
            if (pi.Process != IntPtr.Zero) Native.CloseHandle(pi.Process);
            outerJob?.Dispose();
            job?.Dispose(); image?.Dispose(); stdout?.Dispose(); stderr?.Dispose();
        }
    }

    public void Resume(Action<LaunchStage>? observe = null)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (resumed) throw new InvalidOperationException("TARGET_ALREADY_RESUMED");
            try
            {
                var actual = ReadIdentity(target);
                if (actual.Pid != Identity.TargetPid || actual.Created != Identity.TargetCreatedFileTime
                    || !SamePath(actual.Path, Identity.Executable) || actual.Sid != Identity.UserSid
                    || actual.Session != Identity.SessionId || !IsMember(target, job))
                    throw new InvalidOperationException("PRE_RESUME_IDENTITY_OR_MEMBERSHIP_CHANGED");
                observe?.Invoke(LaunchStage.BeforeResume);
                // Only this method holds the primary-thread resume capability.
                Native.Require(Native.ResumeThread(thread) == 1, "RESUME_PRIMARY_THREAD");
                resumed = true;
                observe?.Invoke(LaunchStage.Resumed);
            }
            catch { Abort(); throw; }
        }
    }

    public uint ExitCode
    {
        get { lock (gate) { ObjectDisposedException.ThrowIf(disposed, this);
            Native.Require(Native.GetExitCodeProcess(target, out var code), "EXIT_CODE"); return code; } }
    }

    public Task WaitForExitAsync(CancellationToken cancellation = default) => Task.Run(() =>
    {
        while (true)
        {
            cancellation.ThrowIfCancellationRequested();
            lock (gate)
            {
                ObjectDisposedException.ThrowIf(disposed, this);
                var value = Native.WaitForSingleObject(target, 0);
                if (value == 0) return;
                Native.Require(value == 258, "WAIT_TARGET");
            }
            // This wait observes termination only; it never establishes launch containment.
            if (cancellation.WaitHandle.WaitOne(25)) cancellation.ThrowIfCancellationRequested();
        }
    }, cancellation);

    public IReadOnlyList<int> MemberPids()
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            for (var capacity = 64; capacity <= 65536; capacity *= 2)
            {
                var size = 8 + capacity * IntPtr.Size;
                var memory = Marshal.AllocHGlobal(size);
                try
                {
                    if (!Native.QueryInformationJobObject(job, 3, memory, (uint)size, out _))
                    {
                        if (Marshal.GetLastWin32Error() == 234) continue;
                        throw new Win32Exception(Marshal.GetLastWin32Error(), "QUERY_JOB_MEMBERS");
                    }
                    var assigned = Marshal.ReadInt32(memory);
                    var listed = Marshal.ReadInt32(memory, 4);
                    if (listed < 0 || listed > capacity || assigned != listed) continue;
                    return Enumerable.Range(0, listed).Select(i => checked((int)Marshal.ReadIntPtr(memory, 8 + i * IntPtr.Size))).ToArray();
                }
                finally { Marshal.FreeHGlobal(memory); }
            }
            throw new InvalidOperationException("JOB_MEMBERSHIP_SNAPSHOT_UNBOUNDED");
        }
    }

    public (uint Total, uint Active) ProcessAccounting()
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            var memory = Marshal.AllocHGlobal(48);
            try
            {
                Native.Require(Native.QueryInformationJobObject(job, 1, memory, 48, out _), "JOB_ACCOUNTING");
                return (unchecked((uint)Marshal.ReadInt32(memory, 36)), unchecked((uint)Marshal.ReadInt32(memory, 40)));
            }
            finally { Marshal.FreeHGlobal(memory); }
        }
    }

    public ProcessTopologyIdentity InspectMember(int pid)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            using var process = Native.OpenProcess(0x1000 | 0x100000, false, pid);
            Native.Require(!process.IsInvalid, "OPEN_JOB_MEMBER");
            if (!IsMember(process, job)) throw new InvalidOperationException("FOREIGN_PROCESS_NOT_IN_JOB");
            var identity = ProcessTopologyIdentity.Capture(process);
            if (Native.WaitForSingleObject(process, 0) != 258)
                throw new InvalidOperationException("TOPOLOGY_MEMBER_EXITED_DURING_OBSERVATION");
            return identity;
        }
    }

    public void Abort()
    {
        lock (gate)
        {
            if (disposed) return;
            Native.Require(Native.TerminateJobObject(job, 125), "TERMINATE_JOB");
            var deadline = Stopwatch.StartNew();
            while (MemberPids().Count != 0)
            {
                if (deadline.Elapsed > TimeSpan.FromSeconds(10))
                    throw new TimeoutException("JOB_QUIESCENCE_UNPROVEN");
                Thread.Yield();
            }
        }
    }

    public void Dispose()
    {
        lock (gate)
        {
            if (disposed) return;
            try { Abort(); }
            finally
            {
                disposed = true;
                job.Dispose(); thread.Dispose(); target.Dispose(); imageLock.Dispose();
                StandardOutput.Dispose(); StandardError.Dispose();
            }
        }
    }

    internal static bool SamePath(string first, string second) =>
        string.Equals(Path.GetFullPath(first), Path.GetFullPath(second), StringComparison.OrdinalIgnoreCase);

    internal static (int Pid, long Created, string Path, string Sid, int Session) ReadIdentity(KernelHandle handle)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var pid = checked((int)Native.GetProcessId(handle));
        Native.Require(pid > 0, "GET_PROCESS_ID");
        Native.Require(Native.GetProcessTimes(handle, out var birth, out _, out _, out _), "GET_PROCESS_BIRTH");
        var path = new StringBuilder(32768); var size = path.Capacity;
        Native.Require(Native.QueryFullProcessImageNameW(handle, 0, path, ref size), "QUERY_PROCESS_IMAGE");
        Native.Require(Native.ProcessIdToSessionId(pid, out var session), "QUERY_PROCESS_SESSION");
        Native.Require(Native.OpenProcessToken(handle, 8, out var token), "QUERY_PROCESS_TOKEN");
        using (token)
        using (var identity = new WindowsIdentity(token.DangerousGetHandle()))
            return (pid, birth, path.ToString(), identity.User?.Value ?? throw new InvalidOperationException("MISSING_USER_SID"), session);
    }

    private static bool IsMember(KernelHandle process, KernelHandle job)
    {
        Native.Require(Native.IsProcessInJob(process, job, out var member), "VERIFY_JOB_MEMBERSHIP");
        return member;
    }

    private static string EnvironmentEntry(string key, string? value)
    {
        if (string.IsNullOrEmpty(key) || key.Contains('\0') || key.Contains('=') || (value?.Contains('\0') ?? false))
            throw new ArgumentException("INVALID_ENVIRONMENT_ENTRY");
        return key + "=" + value;
    }

    internal static string Quote(string argument)
    {
        if (argument.Contains('\0')) throw new ArgumentException("NUL_IN_ARGUMENT");
        var value = new StringBuilder("\""); var slashes = 0;
        foreach (var c in argument)
        {
            if (c == '\\') { slashes++; continue; }
            value.Append('\\', c == '"' ? slashes * 2 + 1 : slashes);
            value.Append(c); slashes = 0;
        }
        return value.Append('\\', slashes * 2).Append('"').ToString();
    }
}

internal sealed class KernelHandle : SafeHandleZeroOrMinusOneIsInvalid
{
    public KernelHandle() : base(true) { }
    public KernelHandle(IntPtr value, bool owns = true) : base(owns) => SetHandle(value);
    protected override bool ReleaseHandle() => Native.CloseHandle(handle);
}

internal static class Native
{
    internal static IReadOnlyList<int> ReadJobPids(KernelHandle job)
    {
        for (var capacity = 64; capacity <= 65536; capacity *= 2)
        {
            var size = 8 + capacity * IntPtr.Size;
            var memory = Marshal.AllocHGlobal(size);
            try
            {
                if (!QueryInformationJobObject(job, 3, memory, (uint)size, out _))
                {
                    if (Marshal.GetLastWin32Error() == 234) continue;
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "QUERY_JOB_MEMBERS");
                }
                var assigned = Marshal.ReadInt32(memory); var listed = Marshal.ReadInt32(memory, 4);
                if (listed < 0 || listed > capacity || assigned != listed) continue;
                return Enumerable.Range(0, listed).Select(i => checked((int)Marshal.ReadIntPtr(memory, 8 + i * IntPtr.Size))).ToArray();
            }
            finally { Marshal.FreeHGlobal(memory); }
        }
        throw new InvalidOperationException("JOB_MEMBERSHIP_SNAPSHOT_UNBOUNDED");
    }
    internal static void Require(bool success, string operation)
    { if (!success) throw new Win32Exception(Marshal.GetLastWin32Error(), operation); }
    [StructLayout(LayoutKind.Sequential)] internal struct SecurityAttributes { public int Length; public IntPtr Descriptor; [MarshalAs(UnmanagedType.Bool)] public bool Inherit; }
    [StructLayout(LayoutKind.Sequential)] internal struct BasicLimits { public long ProcessTime, JobTime; public uint LimitFlags; public UIntPtr MinWorkingSet, MaxWorkingSet; public uint ActiveProcessLimit; public UIntPtr Affinity; public uint PriorityClass, SchedulingClass; }
    [StructLayout(LayoutKind.Sequential)] internal struct IoCounters { public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes; }
    [StructLayout(LayoutKind.Sequential)] internal struct ExtendedLimits { public BasicLimits Basic; public IoCounters Io; public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] internal struct StartupInfo { public int Size; public string? Reserved, Desktop, Title; public uint X,Y,XSize,YSize,XChars,YChars,Fill,Flags; public ushort ShowWindow, ReservedSize; public IntPtr ReservedData,Input,Output,Error; }
    [StructLayout(LayoutKind.Sequential)] internal struct StartupInfoEx { public StartupInfo Startup; public IntPtr Attributes; }
    [StructLayout(LayoutKind.Sequential)] internal struct ProcessInformation { public IntPtr Process, Thread; public int ProcessId, ThreadId; }

    internal sealed class Attributes : IDisposable
    {
        public IntPtr List { get; private set; }
        private bool initialized;
        private readonly List<IntPtr> allocations = new();
        public Attributes(IntPtr[] jobs, IntPtr[] inherit)
        {
            nuint size = 0; InitializeProcThreadAttributeList(IntPtr.Zero, 2, 0, ref size);
            List = Marshal.AllocHGlobal(checked((int)size));
            try
            {
                Require(InitializeProcThreadAttributeList(List, 2, 0, ref size), "INIT_ATTRIBUTES");
                initialized = true;
                Add(0x0002000d, jobs); // JOB_LIST
                Add(0x00020002, inherit); // HANDLE_LIST, excludes Job and process/thread handles.
            }
            catch { Dispose(); throw; }
        }
        private void Add(nuint key, IntPtr[] values)
        {
            var memory = Marshal.AllocHGlobal(values.Length * IntPtr.Size); allocations.Add(memory);
            Marshal.Copy(values, 0, memory, values.Length);
            Require(UpdateProcThreadAttribute(List, 0, key, memory, (nuint)(values.Length * IntPtr.Size), IntPtr.Zero, IntPtr.Zero), "UPDATE_ATTRIBUTES");
        }
        public void Dispose()
        {
            if (List != IntPtr.Zero) { if (initialized) DeleteProcThreadAttributeList(List); Marshal.FreeHGlobal(List); List = IntPtr.Zero; }
            foreach (var memory in allocations) Marshal.FreeHGlobal(memory);
            allocations.Clear();
        }
    }

    [DllImport("kernel32", SetLastError=true, CharSet=CharSet.Unicode)] internal static extern KernelHandle CreateJobObjectW(IntPtr attributes, string? name);
    [DllImport("kernel32", SetLastError=true)] internal static extern bool SetInformationJobObject(KernelHandle job, int kind, ref ExtendedLimits limits, uint size);
    [DllImport("kernel32", SetLastError=true)] internal static extern bool QueryInformationJobObject(KernelHandle job, int kind, IntPtr value, uint size, out uint returned);
    [DllImport("kernel32", SetLastError=true)] internal static extern bool TerminateJobObject(KernelHandle job, uint code);
    [DllImport("kernel32", SetLastError=true)] internal static extern bool IsProcessInJob(KernelHandle process, KernelHandle job, out bool result);
    [DllImport("kernel32", SetLastError=true, CharSet=CharSet.Unicode)] internal static extern bool CreateProcessW(string application, StringBuilder commandLine, IntPtr processAttributes, IntPtr threadAttributes, bool inherit, uint flags, string environment, string directory, ref StartupInfoEx startup, out ProcessInformation process);
    [DllImport("kernel32", SetLastError=true)] internal static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, uint flags, ref nuint bytes);
    [DllImport("kernel32", SetLastError=true)] internal static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, nuint key, IntPtr value, nuint bytes, IntPtr old, IntPtr returned);
    [DllImport("kernel32")] internal static extern void DeleteProcThreadAttributeList(IntPtr list);
    [DllImport("kernel32", SetLastError=true)] internal static extern uint ResumeThread(KernelHandle thread);
    [DllImport("kernel32", SetLastError=true)] internal static extern bool GetProcessTimes(KernelHandle process, out long birth, out long exit, out long kernel, out long user);
    [DllImport("kernel32", SetLastError=true)] internal static extern uint GetProcessId(KernelHandle process);
    [DllImport("kernel32", SetLastError=true)] internal static extern bool ProcessIdToSessionId(int pid, out int session);
    [DllImport("kernel32", SetLastError=true, CharSet=CharSet.Unicode)] internal static extern bool QueryFullProcessImageNameW(KernelHandle process, uint flags, StringBuilder path, ref int size);
    [DllImport("kernel32", SetLastError=true)] internal static extern uint WaitForSingleObject(KernelHandle handle, uint milliseconds);
    [DllImport("kernel32", SetLastError=true)] internal static extern bool GetExitCodeProcess(KernelHandle process, out uint code);
    [DllImport("advapi32", SetLastError=true)] internal static extern bool OpenProcessToken(KernelHandle process, uint access, out KernelHandle token);
    [DllImport("kernel32", SetLastError=true, CharSet=CharSet.Unicode)] internal static extern SafeFileHandle CreateFileW(string path, uint access, uint share, ref SecurityAttributes attributes, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32", SetLastError=true)] internal static extern KernelHandle OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32", SetLastError=true)] internal static extern bool DuplicateHandle(KernelHandle sourceProcess, IntPtr sourceHandle, IntPtr targetProcess, out KernelHandle targetHandle, uint access, bool inherit, uint options);
    [DllImport("kernel32")] internal static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32", SetLastError=true)] internal static extern bool CloseHandle(IntPtr handle);
}
