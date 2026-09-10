using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace MomentumHunter.AutomationService;

public sealed record ProcessTopologyIdentity(int Pid, int ParentPid, long CreatedFileTime,
    string Executable, string ExecutableSha256, string CommandLine, string UserSid, int SessionId)
{
    internal static ProcessTopologyIdentity Capture(KernelHandle retained)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var actual = WindowsContainedProcess.ReadIdentity(retained);
        // WMI reads only this exact retained process's public Win32_Process metadata.
        // The retained object/birth is checked again; WMI absence or ambiguity fails closed.
        dynamic locator = Activator.CreateInstance(Type.GetTypeFromProgID("WbemScripting.SWbemLocator")
            ?? throw new InvalidOperationException("WMI_UNAVAILABLE"))!;
        object? serviceObject = null, rowsObject = null;
        try
        {
            dynamic service = locator.ConnectServer(".", "root\\cimv2"); serviceObject = service;
            dynamic rows = service.ExecQuery("SELECT ProcessId,ParentProcessId,CommandLine,CreationDate FROM Win32_Process WHERE ProcessId=" + actual.Pid);
            rowsObject = rows;
            ProcessTopologyIdentity? result = null;
            foreach (dynamic row in rows)
            {
                try
                {
                    if (result is not null) throw new InvalidOperationException("AMBIGUOUS_PROCESS_TOPOLOGY");
                    var pid = Convert.ToInt32(row.Properties_.Item("ProcessId").Value);
                    var parent = Convert.ToInt32(row.Properties_.Item("ParentProcessId").Value);
                    string command = row.Properties_.Item("CommandLine").Value ?? throw new InvalidOperationException("PROCESS_ARGUMENTS_UNAVAILABLE");
                    string birth = row.Properties_.Item("CreationDate").Value ?? throw new InvalidOperationException("PROCESS_BIRTH_UNAVAILABLE");
                    var date = DateTime.ParseExact(birth[..21], "yyyyMMddHHmmss.ffffff",
                        System.Globalization.CultureInfo.InvariantCulture);
                    var offset = int.Parse(birth[22..], System.Globalization.CultureInfo.InvariantCulture) * (birth[21] == '-' ? -1 : 1);
                    var born = new DateTimeOffset(date, TimeSpan.FromMinutes(offset)).UtcDateTime.ToFileTimeUtc();
                    // CIM birth is microsecond resolution; native FILETIME remains authoritative.
                    if (pid != actual.Pid || born / 10 != actual.Created / 10)
                        throw new InvalidOperationException("PROCESS_PID_REUSE_OR_BIRTH_MISMATCH");
                    result = new(pid, parent, actual.Created, actual.Path,
                        Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(actual.Path))),
                        command, actual.Sid, actual.Session);
                }
                finally { Marshal.FinalReleaseComObject(row); }
            }
            var final = WindowsContainedProcess.ReadIdentity(retained);
            if (final.Pid != actual.Pid || final.Created != actual.Created)
                throw new InvalidOperationException("PROCESS_IDENTITY_CHANGED");
            return result ?? throw new InvalidOperationException("PROCESS_TOPOLOGY_UNAVAILABLE");
        }
        finally
        {
            if (rowsObject is not null) Marshal.FinalReleaseComObject(rowsObject);
            if (serviceObject is not null) Marshal.FinalReleaseComObject(serviceObject);
            Marshal.FinalReleaseComObject(locator);
        }
    }

    public static ProcessTopologyIdentity Capture(int pid, long expectedCreatedFileTime)
    {
        using var process = Native.OpenProcess(0x1000 | 0x100000, false, pid);
        Native.Require(!process.IsInvalid, "OPEN_TOPOLOGY_PROCESS");
        var identity = WindowsContainedProcess.ReadIdentity(process);
        if (identity.Created != expectedCreatedFileTime) throw new InvalidOperationException("STALE_OR_REUSED_PID");
        return Capture(process);
    }

    public static void ValidateSuspended(ContainedIdentity expected, ProcessTopologyIdentity actual,
        IReadOnlyList<int> members)
    {
        if (members.Count != 1 || members[0] != expected.TargetPid
            || actual.Pid != expected.TargetPid || actual.ParentPid != expected.LauncherPid
            || actual.CreatedFileTime != expected.TargetCreatedFileTime
            || actual.CreatedFileTime < expected.LauncherCreatedFileTime
            || !WindowsContainedProcess.SamePath(actual.Executable, expected.Executable)
            || actual.ExecutableSha256 != expected.ExecutableSha256
            || actual.CommandLine != expected.CommandLine || actual.UserSid != expected.UserSid
            || actual.SessionId != expected.SessionId || !expected.ContainmentConfirmed)
            throw new InvalidOperationException("EXACT_SUSPENDED_TOPOLOGY_REJECTED");
    }
}
