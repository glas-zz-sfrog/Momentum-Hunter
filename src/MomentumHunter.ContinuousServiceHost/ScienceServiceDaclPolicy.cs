using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Runtime.InteropServices;
using System.ComponentModel;

namespace MomentumHunter.ContinuousServiceHost;

// Pure planning only. The Science executable acquires no DACL-setting capability.
[System.Runtime.Versioning.SupportedOSPlatform("windows")]
internal static class ScienceServiceDaclPolicy
{
    internal const int ObservedGrantMask = 0x2018d;
    internal static readonly string[] Targets =
        ["MomentumHunterAutomation", "MomentumHunterContinuousRuntime", "MomentumHunterContinuousWriter"];

    internal static string ServiceSid(string name)
    {
        if (name != "MomentumHunterContinuousScience" &&
            !Regex.IsMatch(name, "^MomentumHunterContinuous-qual-[a-z0-9][a-z0-9-]{0,31}-Science$"))
            throw new InvalidDataException("SCIENCE_SERVICE_NAME_NOT_ADMITTED");
        var hash = SHA1.HashData(Encoding.Unicode.GetBytes(name.ToUpperInvariant()));
        return "S-1-5-80-" + string.Join("-", Enumerable.Range(0, 5).Select(i => BitConverter.ToUInt32(hash, 4 * i)));
    }

    internal static string Plan(string target, string scienceName, string scienceSid, string beforeSddl)
    {
        if (!Targets.Contains(target, StringComparer.Ordinal) || ServiceSid(scienceName) != scienceSid)
            throw new InvalidDataException("EXACT_SERVICE_DACL_SCOPE_NOT_BOUND");
        var before = new RawSecurityDescriptor(beforeSddl);
        if (before.Owner == null || before.Group == null || before.DiscretionaryAcl == null ||
            before.Owner.Value == scienceSid ||
            (before.ControlFlags & ControlFlags.DiscretionaryAclPresent) == 0)
            throw new InvalidDataException("COMPLETE_SERVICE_BEFORE_DESCRIPTOR_REQUIRED");
        var observedServiceGrant = false;
        var seenAllow = false;
        var insert = 0;
        foreach (GenericAce ace in before.DiscretionaryAcl)
        {
            if (ace is not CommonAce entry || entry.IsCallback || entry.AceFlags != AceFlags.None ||
                entry.AceQualifier is not (AceQualifier.AccessAllowed or AceQualifier.AccessDenied))
                throw new InvalidDataException("UNREVIEWED_SERVICE_ACE_FORM");
            if (entry.SecurityIdentifier.Value == scienceSid)
                throw new InvalidDataException("SCIENCE_SPECIFIC_ACE_ALREADY_PRESENT_REVIEW_REQUIRED");
            if (entry.AceQualifier == AceQualifier.AccessAllowed) seenAllow = true;
            else if (seenAllow) throw new InvalidDataException("NONCANONICAL_SERVICE_DACL");
            else insert++;
            if (entry.SecurityIdentifier.Value == "S-1-5-6" && entry.AceQualifier == AceQualifier.AccessAllowed)
            {
                if (entry.AccessMask != ObservedGrantMask || observedServiceGrant)
                    throw new InvalidDataException("SERVICE_GRANT_DIFFERS_FROM_REVIEWED_FINDING");
                observedServiceGrant = true;
            }
        }
        if (!observedServiceGrant) throw new InvalidDataException("PROVEN_SERVICE_GRANT_MISSING");
        before.DiscretionaryAcl.InsertAce(insert, new CommonAce(AceFlags.None, AceQualifier.AccessDenied,
            ObservedGrantMask, new SecurityIdentifier(scienceSid), false, null));
        return Render(before);
    }

    internal static void VerifyDelta(string beforeSddl, string afterSddl, string scienceSid)
    {
        var before = new RawSecurityDescriptor(beforeSddl);
        var after = new RawSecurityDescriptor(afterSddl);
        if (before.Owner?.Value != after.Owner?.Value || before.Group?.Value != after.Group?.Value || before.ControlFlags != after.ControlFlags ||
            !Bytes(before.SystemAcl).SequenceEqual(Bytes(after.SystemAcl)) || before.DiscretionaryAcl == null || after.DiscretionaryAcl == null)
            throw new InvalidDataException("NON_DACL_SECURITY_CHANGE");
        var retained = new List<byte[]>();
        var additions = 0;
        foreach (GenericAce ace in after.DiscretionaryAcl)
        {
            if (ace is CommonAce entry && entry.AceQualifier == AceQualifier.AccessDenied && entry.AceFlags == AceFlags.None &&
                !entry.IsCallback && entry.AccessMask == ObservedGrantMask && entry.SecurityIdentifier.Value == scienceSid)
                additions++;
            else retained.Add(Bytes(ace));
        }
        if (additions != 1 || retained.Count != before.DiscretionaryAcl.Count ||
            !retained.Zip(before.DiscretionaryAcl.Cast<GenericAce>(), (a, b) => a.SequenceEqual(Bytes(b))).All(equal => equal))
            throw new InvalidDataException("UNRELATED_SERVICE_ACE_CHANGE");
    }

    private static byte[] Bytes(GenericAce ace) { var result = new byte[ace.BinaryLength]; ace.GetBinaryForm(result, 0); return result; }
    private static byte[] Bytes(GenericAcl? acl) { if (acl == null) return []; var result = new byte[acl.BinaryLength]; acl.GetBinaryForm(result, 0); return result; }
    internal static string Render(RawSecurityDescriptor descriptor)
    {
        var bytes = new byte[descriptor.BinaryLength];
        descriptor.GetBinaryForm(bytes, 0);
        // .NET GetSddlForm(All) omits mandatory-label ACEs. Preserve them natively.
        if (!ConvertSecurityDescriptorToStringSecurityDescriptorW(bytes, 1, 0x1f, out var text, out _))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "COMPLETE_SERVICE_SDDL_SERIALIZATION");
        try { return Marshal.PtrToStringUni(text)!; }
        finally { LocalFree(text); }
    }
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool ConvertSecurityDescriptorToStringSecurityDescriptorW(byte[] descriptor, uint version, uint information, out nint text, out uint length);
    [DllImport("kernel32.dll")] private static extern nint LocalFree(nint memory);
}
