namespace MomentumHunter.ContinuousServiceHost;

internal sealed record ScmRestrictedServiceProvenance(string ServiceName, string ServiceSid, int ServiceSidType, uint ProcessId);

[System.Runtime.Versioning.SupportedOSPlatform("windows")]
internal static class DirectScienceTokenContract
{
    internal static string[] Failures(TokenObservation token, ThreadTokenObservation thread, string serviceName,
        ScmRestrictedServiceProvenance? provenance = null)
    {
        var failures = new List<string>();
        var sid = ScienceServiceDaclPolicy.ServiceSid(serviceName);
        if (provenance == null || provenance.ServiceName != serviceName || provenance.ServiceSid != sid ||
            provenance.ServiceSidType != 3 || provenance.ProcessId == 0 || provenance.ProcessId != token.ProcessId)
            failures.Add("SCM_WRITE_RESTRICTED_SERVICE_PROVENANCE_UNPROVEN");
        if (!token.Complete || !thread.ExpectedByLauncher) failures.Add("NATIVE_TOKEN_PROOF_INCOMPLETE_OR_IMPERSONATION_PRESENT");
        if (token.Type != 1 || token.User?.Sid != sid || token.SessionId != 0 || token.UiAccess != 0)
            failures.Add("SCM_PRIMARY_SERVICE_IDENTITY_MISMATCH");
        // SCM virtual-account elevation metadata is not a UAC-administrator token.
        // This separate contract never relaxes the historical child-token guard.
        if (token.ElevationType != 1 || token.Elevated != 0 || token.Virtualization != 0 || token.Integrity?.Sid != "S-1-16-12288")
            failures.Add("UNEXPECTED_SCM_TOKEN_CLASS");
        var logons = token.LogonSids ?? [];
        var expected = new HashSet<string>(StringComparer.Ordinal) { sid, "S-1-1-0", "S-1-5-33" };
        if (logons.Length != 1 || !System.Text.RegularExpressions.Regex.IsMatch(logons[0].Sid, @"\AS-1-5-5-[0-9]+-[0-9]+\z") ||
            (logons[0].Attributes & 0xc0000007u) != 0xc0000007u || (logons[0].Attributes & ~0xc000000fu) != 0)
            failures.Add("SCM_LOGON_SID_UNPROVEN");
        else expected.Add(logons[0].Sid);
        var restricting = token.RestrictingSids ?? [];
        if (token.Restricted != true || token.HasRestrictions != 1 ||
            !expected.SetEquals(restricting.Select(s => s.Sid)) || restricting.Length != expected.Count ||
            restricting.Any(s => s.Attributes != 7))
            failures.Add("SCM_WRITE_RESTRICTED_SID_SET_MISMATCH");
        var ordinary = token.Groups ?? [];
        if (ordinary.Count(s => s.Sid == "S-1-5-33" && s.Attributes == 7) != 1 ||
            ordinary.Count(s => s.Sid == "S-1-5-33") != 1 ||
            ordinary.Count(s => s.Sid == "S-1-1-0" && s.Attributes == 7) != 1 ||
            logons.Length != 1 || ordinary.Count(s => s == logons[0]) != 1 ||
            ordinary.Select(s => s.Sid).Distinct(StringComparer.Ordinal).Count() != ordinary.Length)
            failures.Add("SCM_WRITE_RESTRICTED_GROUP_RELATIONSHIP_MISMATCH");
        var allowed = new HashSet<string>(StringComparer.Ordinal) {
            sid, "S-1-1-0", "S-1-2-0", "S-1-2-1", "S-1-5-6", "S-1-5-11", "S-1-5-15",
            "S-1-5-32-545", "S-1-5-80-0", "S-1-16-12288"
        };
        foreach (var logon in logons) allowed.Add(logon.Sid);
        if (!ordinary.Any(s => s.Sid == "S-1-5-6" && (s.Attributes & 4) != 0))
            failures.Add("SERVICE_LOGON_GROUP_NOT_ENABLED");
        if (token.Privileges is not { Length: 1 } || token.Privileges[0].Name != "SeChangeNotifyPrivilege" ||
            token.Privileges[0].Luid != 23 || token.Privileges[0].Attributes != 3)
            failures.Add("EXCESS_OR_UNPROVEN_SCM_PRIVILEGE");
        // This marker is expected in BOTH native categories only for the complete,
        // live-owner-bound SCM contract. It is never added to the ordinary allowlist.
        var writeRestrictedService = failures.Count == 0;
        if (ordinary.Any(s => !allowed.Contains(s.Sid) && !(writeRestrictedService && s.Sid == "S-1-5-33")))
            failures.Add("UNREVIEWED_SERVICE_GROUP_AUTHORITY");
        return failures.ToArray();
    }
}
