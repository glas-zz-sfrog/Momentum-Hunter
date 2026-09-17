using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.Principal;
using System.Text;

namespace MomentumHunter.ContinuousServiceHost;

internal sealed record TokenApiResult(string Api, bool Success, int? Win32Error = null,
    int? NtStatus = null, uint? InformationClass = null, uint? Length = null, bool? BooleanReturn = null,
    uint? RequestedSize = null, string? RawPayloadHex = null, string? QueryContract = null,
    int? NativeLastError = null);
internal sealed record TokenSid(string Sid, uint Attributes);
internal sealed record TokenPrivilege(string Name, long Luid, uint Attributes);
internal sealed record TokenIds(long TokenId, long AuthenticationId, long ModifiedId);
internal sealed record TokenObservation
{
    public required string Stage { get; init; }
    public required string Source { get; init; }
    public required string ProducingApi { get; init; }
    public uint? RequestedAccess { get; init; }
    public DateTimeOffset CapturedAt { get; init; } = DateTimeOffset.UtcNow;
    public uint ProcessId { get; init; }
    public uint ThreadId { get; init; }
    public int? Type { get; set; }
    public int? ImpersonationLevel { get; set; }
    public string ImpersonationLevelApplicability { get; set; } = "UNKNOWN";
    public int? ElevationType { get; set; }
    public int? Elevated { get; set; }
    public int? SessionId { get; set; }
    public int? UiAccess { get; set; }
    public int? Virtualization { get; set; }
    public int? HasRestrictions { get; set; }
    public bool? Restricted { get; set; }
    public string RestrictedState { get; set; } = "NOT_OBSERVED";
    public uint? GrantedAccess { get; set; }
    public TokenSid? User { get; set; }
    public TokenSid? Integrity { get; set; }
    public TokenSid[]? Groups { get; set; }
    public TokenSid[]? LogonSids { get; set; }
    public TokenSid[]? RestrictingSids { get; set; }
    public TokenPrivilege[]? Privileges { get; set; }
    public TokenIds? Ids { get; set; }
    public List<TokenApiResult> Calls { get; } = [];
    public List<string> Errors { get; } = [];
    public bool Complete => Errors.Count == 0 && Type is 1 or 2 && ElevationType is >= 1 and <= 3
        && Elevated is 0 or 1 && SessionId >= 0 && UiAccess is 0 or 1 && Virtualization is 0 or 1
        && HasRestrictions is 0 or 1 && Restricted != null && RestrictedState == "KNOWN" && GrantedAccess != null
        && User != null && Integrity != null && Groups != null && LogonSids != null
        && RestrictingSids != null && Privileges != null && Ids != null
        && (Type == 1 ? ImpersonationLevelApplicability == "NOT_APPLICABLE_PRIMARY_TOKEN"
            : ImpersonationLevel is >= 0 and <= 3 && ImpersonationLevelApplicability == "NATIVE_SECURITY_IMPERSONATION_LEVEL");
}

internal sealed record ThreadTokenObservation(string Stage, uint ThreadId, string Presence,
    string Provenance, TokenApiResult OpenResult, TokenObservation? Token)
{
    public bool ExpectedByLauncher => Presence == "ABSENT" && !OpenResult.Success && OpenResult.Win32Error == 1008;
}

// The fake used by the offline probe implements EVERY member. There is no native fallback.
internal interface IWindowsTokenQueries
{
    uint ProcessId { get; }
    uint ThreadId { get; }
    TokenApiResult Information(IntPtr token, int kind, IntPtr data, uint size, out uint needed);
    TokenApiResult Access(IntPtr token, out uint granted);
    TokenApiResult Restricted(IntPtr token, out bool? restricted);
    TokenApiResult PrivilegeName(ref long luid, StringBuilder name, ref uint length);
    TokenApiResult OpenThread(out IntPtr token);
    TokenApiResult OpenProcess(uint access, out IntPtr token);
    void Close(IntPtr token);
}

[SupportedOSPlatform("windows")]
internal sealed class NativeWindowsTokenQueries : IWindowsTokenQueries
{
    public uint ProcessId => GetCurrentProcessId();
    public uint ThreadId => GetCurrentThreadId();
    public TokenApiResult Information(IntPtr token, int kind, IntPtr data, uint size, out uint needed)
    {
        var ok = GetTokenInformation(token, kind, data, size, out needed);
        var error = Marshal.GetLastWin32Error();
        return new("GetTokenInformation", ok, ok ? null : error, InformationClass: (uint)kind,
            Length: needed, BooleanReturn: ok, RequestedSize: size, NativeLastError: error);
    }
    public TokenApiResult Access(IntPtr token, out uint granted)
    {
        granted = 0;
        try
        {
            var status = NtQueryObject(token, 0, out var basic, (uint)Marshal.SizeOf<ObjectBasicInformation>(), out var size);
            if (status >= 0) granted = basic.GrantedAccess;
            // NtQueryObject returns NTSTATUS, NOT GetLastError. Never invent a Win32 error here.
            return new("NtQueryObject(ObjectBasicInformation)", status >= 0 && size >= 8, NtStatus: status, Length: size);
        }
        catch (Exception ex) when (ex is DllNotFoundException or EntryPointNotFoundException)
        { return new("NtQueryObject unavailable: " + ex.GetType().Name, false); }
    }
    public TokenApiResult Restricted(IntPtr token, out bool? restricted)
    {
        // On .NET, SetLastError=true clears the native error before the call and
        // caches it afterward. FALSE with zero is a valid unrestricted result.
        var raw = IsTokenRestricted(token);
        var error = Marshal.GetLastWin32Error();
        return RestrictedResult(raw, error, out restricted);
    }
    internal static TokenApiResult RestrictedResult(bool raw, int error, out bool? restricted)
    {
        var success = raw || error == 0;
        restricted = success ? raw : null;
        return new("IsTokenRestricted", success, success ? null : error, BooleanReturn: raw);
    }
    public TokenApiResult PrivilegeName(ref long luid, StringBuilder name, ref uint length)
    {
        var ok = LookupPrivilegeNameW(null, ref luid, name, ref length);
        var error = ok ? (int?)null : Marshal.GetLastWin32Error();
        return new("LookupPrivilegeNameW", ok, error, Length: length);
    }
    public TokenApiResult OpenThread(out IntPtr token)
    {
        var ok = OpenThreadToken(GetCurrentThread(), 0x8, true, out token);
        var error = ok ? (int?)null : Marshal.GetLastWin32Error();
        return new("OpenThreadToken(TOKEN_QUERY, OpenAsSelf=true)", ok, error);
    }
    public TokenApiResult OpenProcess(uint access, out IntPtr token)
    {
        var ok = OpenProcessToken(GetCurrentProcess(), access, out token);
        var error = ok ? (int?)null : Marshal.GetLastWin32Error();
        return new("OpenProcessToken(current process)", ok, error);
    }
    public void Close(IntPtr token) => CloseHandle(token);
    [StructLayout(LayoutKind.Sequential)] private struct ObjectBasicInformation
    {
        public uint Attributes, GrantedAccess, HandleCount, PointerCount;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 10)] public uint[] Reserved;
    }
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool GetTokenInformation(IntPtr token, int kind, IntPtr data, uint size, out uint needed);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool IsTokenRestricted(IntPtr token);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool LookupPrivilegeNameW(string? system, ref long luid, StringBuilder name, ref uint size);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool OpenThreadToken(IntPtr thread, uint access, bool openAsSelf, out IntPtr token);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
    [DllImport("ntdll.dll")] private static extern int NtQueryObject(IntPtr handle, int kind, out ObjectBasicInformation info, uint length, out uint returned);
    [DllImport("kernel32.dll")] private static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll")] private static extern IntPtr GetCurrentThread();
    [DllImport("kernel32.dll")] private static extern uint GetCurrentProcessId();
    [DllImport("kernel32.dll")] private static extern uint GetCurrentThreadId();
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
}

[SupportedOSPlatform("windows")]
internal sealed class WindowsScienceTokenInspection(IWindowsTokenQueries api)
{
    public TokenObservation Capture(IntPtr token, string stage, string source, string producer, uint? requestedAccess)
    {
        var value = new TokenObservation { Stage = stage, Source = source, ProducingApi = producer,
            RequestedAccess = requestedAccess, ProcessId = api.ProcessId, ThreadId = api.ThreadId };
        value.Type = Scalar(8);
        if (value.Type == 1) value.ImpersonationLevelApplicability = "NOT_APPLICABLE_PRIMARY_TOKEN";
        else if (value.Type == 2)
        {
            value.ImpersonationLevelApplicability = "NATIVE_SECURITY_IMPERSONATION_LEVEL";
            value.ImpersonationLevel = Scalar(9); // Native: Anonymous=0, Identification=1, Impersonation=2, Delegation=3.
        }
        else value.Errors.Add("TOKEN_TYPE_UNPROVEN");
        value.ElevationType = Scalar(18);
        value.Elevated = FixedBoolean(20);
        value.SessionId = Scalar(12);
        value.UiAccess = Scalar(26);
        value.Virtualization = Scalar(24);
        value.HasRestrictions = FixedBoolean(21);
        value.User = Read<TokenSid>(1, (p, n) => Sid(p, p, n));
        value.Integrity = Read<TokenSid>(25, (p, n) => Sid(p, p, n));
        value.Groups = Groups(2);
        value.LogonSids = Groups(28);
        value.RestrictingSids = Groups(11);
        value.Ids = Read<TokenIds>(10, (p, n) =>
        {
            Require(n >= 56, "SHORT_TOKEN_STATISTICS");
            return new(Marshal.ReadInt64(p), Marshal.ReadInt64(p, 8), Marshal.ReadInt64(p, 48));
        });
        value.Privileges = Read<TokenPrivilege[]>(3, (p, n) =>
        {
            Require(n >= 4, "SHORT_PRIVILEGES");
            var count = Marshal.ReadInt32(p);
            Require(count >= 0 && count <= (n - 4) / 12, "INVALID_PRIVILEGE_COUNT");
            return Enumerable.Range(0, count).Select(i =>
            {
                var row = IntPtr.Add(p, 4 + 12 * i);
                var luid = Marshal.ReadInt64(row);
                var name = new StringBuilder(256);
                uint length = 256;
                var call = api.PrivilegeName(ref luid, name, ref length);
                value.Calls.Add(call);
                if (!call.Success) throw new InvalidDataException("PRIVILEGE_NAME_UNPROVEN");
                return new TokenPrivilege(name.ToString(), luid, unchecked((uint)Marshal.ReadInt32(row, 8)));
            }).ToArray();
        });
        var restriction = api.Restricted(token, out var restricted);
        value.Calls.Add(restriction);
        if (restriction.Success && restricted != null)
        {
            value.Restricted = restricted;
            value.RestrictedState = "KNOWN";
        }
        else
        {
            value.RestrictedState = "UNKNOWN_QUERY_FAILED";
            value.Errors.Add("IS_TOKEN_RESTRICTED_QUERY_FAILED");
        }
        var access = api.Access(token, out var granted);
        value.Calls.Add(access);
        if (access.Success) value.GrantedAccess = granted;
        else value.Errors.Add("HANDLE_GRANTED_ACCESS_UNPROVEN");
        return value;

        int? Scalar(int kind) => Read<int?>(kind, (p, n) =>
        { Require(n >= 4, "SHORT_SCALAR"); return Marshal.ReadInt32(p); });
        int? FixedBoolean(int kind)
        {
            Require(kind is 20 or 21, "UNSUPPORTED_FIXED_BOOLEAN_CLASS");
            const uint size = sizeof(uint); // TOKEN_ELEVATION and documented TokenHasRestrictions DWORD.
            var memory = Marshal.AllocHGlobal((int)size);
            try
            {
                // Unwritten bytes must not become a fabricated zero/known-false observation.
                Marshal.WriteInt32(memory, -1);
                var query = api.Information(token, kind, memory, size, out var returned);
                var raw = new byte[(int)Math.Min(size, returned)];
                Marshal.Copy(memory, raw, 0, raw.Length);
                var contract = kind == 20 ? "TOKEN_ELEVATION_DWORD_V1"
                    : returned == 1 ? "TOKEN_HAS_RESTRICTIONS_BYTE_COMPAT_V1"
                    : "TOKEN_HAS_RESTRICTIONS_DWORD_V1";
                value.Calls.Add(query with { RequestedSize = size, Length = returned,
                    RawPayloadHex = Convert.ToHexString(raw), QueryContract = contract });
                if (!query.Success)
                { value.Errors.Add($"QUERY_{kind}_FAILED"); return null; }
                if (returned != size && !(kind == 21 && returned == 1))
                { value.Errors.Add($"QUERY_{kind}_INVALID_FIXED_LENGTH:{returned}"); return null; }
                // Class21 alone has a measured one-byte ABI; never read or zero-extend its tail.
                var decoded = returned == 1 ? Marshal.ReadByte(memory) : Marshal.ReadInt32(memory);
                if (decoded is not (0 or 1))
                { value.Errors.Add($"QUERY_{kind}_UNSUPPORTED_BOOLEAN:{decoded}"); return null; }
                return decoded;
            }
            finally { Marshal.FreeHGlobal(memory); }
        }
        TokenSid[]? Groups(int kind) => Read<TokenSid[]>(kind, (p, n) =>
        {
            Require(n >= 4, "SHORT_GROUPS");
            var count = Marshal.ReadInt32(p);
            var rowSize = Marshal.SizeOf<SidAttributes>();
            Require(count >= 0 && (count == 0 || count <= (n - IntPtr.Size) / rowSize), "INVALID_GROUP_COUNT");
            return Enumerable.Range(0, count).Select(i => Sid(IntPtr.Add(p, IntPtr.Size + i * rowSize), p, n)).ToArray();
        });
        T? Read<T>(int kind, Func<IntPtr, int, T> decode)
        {
            var sizing = api.Information(token, kind, IntPtr.Zero, 0, out var needed);
            value.Calls.Add(sizing);
            if (sizing.Success || sizing.Win32Error != 122 || needed == 0 || needed > 1024 * 1024)
            { value.Errors.Add($"QUERY_{kind}_SIZE_UNPROVEN"); return default; }
            var memory = Marshal.AllocHGlobal((int)needed);
            try
            {
                var query = api.Information(token, kind, memory, needed, out var returned);
                value.Calls.Add(query);
                if (!query.Success || returned > needed || returned == 0)
                { value.Errors.Add($"QUERY_{kind}_FAILED"); return default; }
                try { return decode(memory, (int)returned); }
                catch (Exception ex) when (ex is InvalidDataException or ArgumentException or OverflowException)
                { value.Errors.Add($"QUERY_{kind}_DECODE_FAILED:{ex.Message}"); return default; }
            }
            finally { Marshal.FreeHGlobal(memory); }
        }
    }

    public ThreadTokenObservation CaptureThread(string stage)
    {
        var threadId = api.ThreadId;
        var opened = api.OpenThread(out var handle);
        if (!opened.Success)
            return new(stage, threadId, opened.Win32Error == 1008 ? "ABSENT" : "UNKNOWN",
                "Current native thread; origin of any pre-existing impersonation is not inferred", opened, null);
        try
        {
            return new(stage, threadId, "PRESENT", "OpenThreadToken current native thread; initiating impersonation API UNKNOWN",
                opened, Capture(handle, stage + "-token", "current-thread", opened.Api, 0x8));
        }
        finally { api.Close(handle); }
    }

    public TokenObservation CaptureCurrentProcess(string stage)
    {
        const uint rights = 0xE; // QUERY for observation, DUPLICATE|IMPERSONATE for the documented caller contract.
        var opened = api.OpenProcess(rights, out var handle);
        if (!opened.Success)
        {
            var failed = new TokenObservation { Stage = stage, Source = "current-process", ProducingApi = opened.Api,
                RequestedAccess = rights, ProcessId = api.ProcessId, ThreadId = api.ThreadId };
            failed.Calls.Add(opened);
            failed.Errors.Add("CURRENT_PROCESS_TOKEN_OPEN_FAILED");
            return failed;
        }
        try
        {
            var result = Capture(handle, stage, "current-process", opened.Api, rights);
            result.Calls.Insert(0, opened);
            return result;
        }
        finally { api.Close(handle); }
    }

    private static TokenSid Sid(IntPtr row, IntPtr start, int length)
    {
        var offset = row.ToInt64() - start.ToInt64();
        Require(offset >= 0 && offset + Marshal.SizeOf<SidAttributes>() <= length, "SID_ROW_OUT_OF_BOUNDS");
        var data = Marshal.PtrToStructure<SidAttributes>(row);
        var sidOffset = data.Sid.ToInt64() - start.ToInt64();
        Require(sidOffset >= 0 && sidOffset + 8 <= length, "SID_OUT_OF_BOUNDS");
        var size = 8 + 4 * Marshal.ReadByte(data.Sid, 1);
        Require(sidOffset + size <= length, "SID_LENGTH_OUT_OF_BOUNDS");
        return new(new SecurityIdentifier(data.Sid).Value, data.Attributes);
    }
    private static void Require(bool condition, string message)
    { if (!condition) throw new InvalidDataException(message); }
    [StructLayout(LayoutKind.Sequential)] private struct SidAttributes { public IntPtr Sid; public uint Attributes; }
}
