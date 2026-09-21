using System.Security.AccessControl;
using MomentumHunter.ContinuousServiceHost;

const string name = "MomentumHunterContinuous-qual-013b-r011-214611-Science";
const string sid = "S-1-5-80-2360323399-3885101186-852604897-3857439045-1863769236";
const string logon = "S-1-5-5-0-123";
const string before = "O:SYG:SYD:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)(A;;CCLCSWLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU)S:(ML;;NW;;;HI)";
var passed = new List<string>();
void Check(bool value, string test) { if (!value) throw new Exception(test); passed.Add(test); }
void Reject(Action run, string test) { try { run(); } catch (InvalidDataException) { passed.Add(test); return; } throw new Exception(test); }
foreach (var version in new[] { 1, 2 })
{
    Check(ScienceMutableCustodyContract.Namespaces(version).Length == (version == 1 ? 9 : 11), "020G-exact-topology-" + version);
    foreach (var right in new uint[] { 2, 4, 16, 64, 256, 65536, 262144, 524288 })
        Check(ScienceMutableCustodyContract.MutableParentRight(version, right) ==
            (right == 2 || (version == 1 && right is 4 or 64)), "020G-parent-right-" + version + "-" + right);
    Check(ScienceMutableCustodyContract.RootPath(@"F:\q\science", "cursors", version) == @"F:\q\science\reader\cursors", "020G-cursor-unchanged-" + version);
}
foreach (var item in new[] { ("owner", @"mutable-v2\owner-lease"), ("derived", @"mutable-v2\reader-lock"),
    ("scratch", @"mutable-v2\transport-scratch"), ("staging", "staging-v2"), ("requests", "requests-v2") })
    Check(ScienceMutableCustodyContract.RootPath(@"F:\q\science", item.Item1, 2) == @"F:\q\science\" + item.Item2, "020G-path-" + item.Item1);
Reject(() => ScienceMutableCustodyContract.Namespaces(3), "020G-version-reject");
Reject(() => ScienceMutableCustodyContract.RootPath(@"F:\q\science", "owner", 1), "020G-v1-v2-isolation");
Reject(() => ScienceMutableCustodyContract.RootPath(@"F:\q\science", "../escape", 2), "020G-path-escape");
Check(ScienceServiceDaclPolicy.ServiceSid(name) == sid, "native-service-sid-control");
foreach (var target in ScienceServiceDaclPolicy.Targets)
{
    var after = ScienceServiceDaclPolicy.Plan(target, name, sid, before);
    ScienceServiceDaclPolicy.VerifyDelta(before, after, sid);
    Check(new RawSecurityDescriptor(after).DiscretionaryAcl!.Count == 5, "exact-one-ACE:" + target);
    Reject(() => ScienceServiceDaclPolicy.Plan(target, name, sid, after), "no-double-application:" + target);
    Reject(() => ScienceServiceDaclPolicy.VerifyDelta(before, after.Replace("O:SY", "O:BA"), sid), "owner-preserved:" + target);
    Reject(() => ScienceServiceDaclPolicy.VerifyDelta(before, after.Replace("G:SY", "G:BA"), sid), "group-preserved:" + target);
    Reject(() => ScienceServiceDaclPolicy.VerifyDelta(before, after.Replace("NW", "NRNW"), sid), "SACL-label-preserved:" + target);
    Reject(() => ScienceServiceDaclPolicy.VerifyDelta(before, after.Replace("CCLCSWLOCRRC;;;IU", "CCLCSWLORC;;;IU"), sid), "unrelated-ACE-preserved:" + target);
}
Reject(() => ScienceServiceDaclPolicy.Plan("OtherService", name, sid, before), "target-allowlist");
Reject(() => ScienceServiceDaclPolicy.Plan(ScienceServiceDaclPolicy.Targets[0], name, "S-1-5-18", before), "no-broad-principal");
Reject(() => ScienceServiceDaclPolicy.Plan(ScienceServiceDaclPolicy.Targets[0], name, sid, before.Replace("CCLCSWLOCRRC;;;SU", "CCLCSWLORC;;;SU")), "grant-drift");
Reject(() => ScienceServiceDaclPolicy.Plan(ScienceServiceDaclPolicy.Targets[0], name, sid, "O:SYG:SY"), "null-DACL-rejected");
Reject(() => ScienceServiceDaclPolicy.Plan(ScienceServiceDaclPolicy.Targets[0], name, sid, before.Replace("O:SY", "O:" + sid)), "Science-owner-rejected");

TokenObservation Good() => new() {
    Stage = "TEST_ONLY", Source = "DECLARED_SYNTHETIC_FIXTURE", ProducingApi = "NONE",
    Type = 1, ImpersonationLevelApplicability = "NOT_APPLICABLE_PRIMARY_TOKEN", ElevationType = 1,
    Elevated = 0, SessionId = 0, UiAccess = 0, Virtualization = 0, HasRestrictions = 1, ProcessId = 4242,
    Restricted = true, RestrictedState = "KNOWN", GrantedAccess = 8, User = new(sid, 0),
    Integrity = new("S-1-16-12288", 96), Groups = [new("S-1-16-12288", 96), new("S-1-1-0", 7),
        new("S-1-5-32-545", 7), new("S-1-5-6", 7), new("S-1-2-1", 7), new("S-1-5-11", 7),
        new("S-1-5-15", 7), new(logon, 0xc000000f), new("S-1-2-0", 7), new("S-1-5-33", 7), new("S-1-5-80-0", 7)],
    LogonSids = [new(logon, 0xc000000f)], RestrictingSids = [new(sid, 7), new("S-1-1-0", 7), new("S-1-5-33", 7), new(logon, 7)],
    Privileges = [new("SeChangeNotifyPrivilege", 23, 3)], Ids = new(1, 2, 3)
};
var thread = new ThreadTokenObservation("TEST", 1, "ABSENT", "FIXTURE", new("OpenThreadToken", false, 1008), null);
var provenance = new ScmRestrictedServiceProvenance(name, sid, 3, 4242);
Check(DirectScienceTokenContract.Failures(Good(), thread, name, provenance).Length == 0, "SCM-specific-positive");
foreach (var mutation in new Action<TokenObservation>[] {
    t => t.User = new("S-1-5-18", 0), t => t.SessionId = 1, t => t.Type = 2,
    t => t.Restricted = false, t => t.RestrictingSids = [], t => t.Groups = [new("S-1-5-32-544", 7)],
    t => t.Privileges = [new("SeChangeNotifyPrivilege", 23, 3), new("SeImpersonatePrivilege", 29, 2)],
    t => t.Privileges = [new("SeChangeNotifyPrivilege", 23, 3), new("SeIncreaseQuotaPrivilege", 5, 0)],
    t => t.LogonSids = [], t => t.Errors.Add("QUERY_UNPROVEN"), t => t.ElevationType = 2,
    t => t.Integrity = new("S-1-16-16384", 96)
})
{
    var token = Good(); mutation(token);
    Check(DirectScienceTokenContract.Failures(token, thread, name, provenance).Length > 0, "token-mutation-" + passed.Count);
}
Check(DirectScienceTokenContract.Failures(Good(), thread with { Presence = "PRESENT" }, name, provenance).Length > 0, "thread-impersonation-rejected");
var guardCases = new List<string> { "exact-restricted-SCM-dual-category-positive" };
foreach (var (caseName, mutate) in new (string, Action<TokenObservation>)[] {
    ("minus-marker-both", t => { t.Groups = t.Groups!.Where(s => s.Sid != "S-1-5-33").ToArray(); t.RestrictingSids = t.RestrictingSids!.Where(s => s.Sid != "S-1-5-33").ToArray(); }),
    ("marker-only-restricting", t => t.Groups = t.Groups!.Where(s => s.Sid != "S-1-5-33").ToArray()),
    ("marker-only-ordinary", t => t.RestrictingSids = t.RestrictingSids!.Where(s => s.Sid != "S-1-5-33").ToArray()),
    ("interactive", t => { t.SessionId = 1; t.Groups = [.. t.Groups!, new("S-1-5-4", 7)]; }),
    ("unrestricted", t => t.Restricted = false),
    ("restrictions-metadata-contradiction", t => t.HasRestrictions = 0),
    ("wrong-service-SID", t => t.User = new("S-1-5-80-1-2-3-4-5", 0)),
    ("wrong-service-restrictor", t => t.RestrictingSids = t.RestrictingSids!.Select(s => s.Sid == sid ? new TokenSid("S-1-5-80-1-2-3-4-5", 7) : s).ToArray()),
    ("extra-unknown-ordinary", t => t.Groups = [.. t.Groups!, new("S-1-5-99", 7)]),
    ("extra-unknown-restricting", t => t.RestrictingSids = [.. t.RestrictingSids!, new("S-1-5-99", 7)]),
    ("dangerous-privilege", t => t.Privileges = [.. t.Privileges!, new("SeDebugPrivilege", 20, 2)]),
    ("LocalSystem", t => t.User = new("S-1-5-18", 0)),
    ("Administrators", t => t.Groups = [.. t.Groups!, new("S-1-5-32-544", 7)]),
    ("elevated", t => t.Elevated = 1),
    ("virtualization", t => t.Virtualization = 1),
    ("marker-ordinary-deny-only", t => t.Groups = t.Groups!.Select(s => s.Sid == "S-1-5-33" ? new TokenSid(s.Sid, 16) : s).ToArray()),
    ("marker-restricting-deny-only", t => t.RestrictingSids = t.RestrictingSids!.Select(s => s.Sid == "S-1-5-33" ? new TokenSid(s.Sid, 16) : s).ToArray()),
    ("duplicate-marker-ordinary", t => t.Groups = [.. t.Groups!, new("S-1-5-33", 7)]),
    ("duplicate-marker-restricting", t => t.RestrictingSids = [.. t.RestrictingSids!, new("S-1-5-33", 7)]),
    ("missing-logon-group", t => t.Groups = t.Groups!.Where(s => s.Sid != logon).ToArray()),
    ("logon-category-spoof", t => t.LogonSids = [new("S-1-5-33", 7)]),
    ("ordinary-power-group-moved-to-restricting", t => t.RestrictingSids = [.. t.RestrictingSids!, new("S-1-5-32-544", 7)]),
    ("wrong-privilege-LUID", t => t.Privileges = [new("SeChangeNotifyPrivilege", 20, 3)]),
    ("unexpected-privilege-attributes", t => t.Privileges = [new("SeChangeNotifyPrivilege", 23, 7)])
})
{
    var token = Good(); mutate(token);
    Check(DirectScienceTokenContract.Failures(token, thread, name, provenance).Length > 0, "015C:" + caseName);
    guardCases.Add(caseName);
}
foreach (var (caseName, invalid) in new (string, ScmRestrictedServiceProvenance?)[] {
    ("missing-service-provenance", null), ("wrong-SCM-SID-type", provenance with { ServiceSidType = 1 }),
    ("wrong-service-name-provenance", provenance with { ServiceName = "OTHER" }),
    ("wrong-service-SID-provenance", provenance with { ServiceSid = "S-1-5-18" }),
    ("wrong-client-PID-provenance", provenance with { ProcessId = 4243 }),
    ("zero-client-PID-provenance", provenance with { ProcessId = 0 })
})
{
    Check(DirectScienceTokenContract.Failures(Good(), thread, name, invalid).Length > 0, "015C:" + caseName);
    guardCases.Add(caseName);
}
Check(DirectScienceTokenContract.Failures(Good(), thread, name).Length > 0, "legacy-caller-has-no-provenance-fallback");
if (args.Length == 3)
{
    using var raw = System.Text.Json.JsonDocument.Parse(File.ReadAllBytes(args[0]));
    using var preactivation = System.Text.Json.JsonDocument.Parse(File.ReadAllBytes(args[1]));
    var observed = System.Text.Json.JsonSerializer.Deserialize<TokenObservation>(raw.RootElement.GetProperty("observed").GetRawText())!;
    var actualThread = System.Text.Json.JsonSerializer.Deserialize<ThreadTokenObservation>(raw.RootElement.GetProperty("thread").GetRawText())!;
    var service = preactivation.RootElement.GetProperty("configurations").EnumerateArray().Single(s => s.GetProperty("Role").GetString() == "Science");
    Check(service.GetProperty("Name").GetString() == args[2], "retained-service-name-bound");
    var replayProvenance = new ScmRestrictedServiceProvenance(args[2], ScienceServiceDaclPolicy.ServiceSid(args[2]),
        service.GetProperty("config").GetProperty("sidType").GetInt32(), observed.ProcessId);
    Check(DirectScienceTokenContract.Failures(observed, actualThread, args[2], replayProvenance).Length == 0,
        "exact-retained-token-and-config-replay-not-new-physical-proof");
}
var temporary = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "MH-014A-Generation-" + Guid.NewGuid().ToString("N")));
var generationRoot = Path.Combine(temporary, "host", "science");
var logRoot = Path.Combine(temporary, "logs", "science");
Directory.CreateDirectory(generationRoot); Directory.CreateDirectory(logRoot);
try
{
    var config = new System.Text.Json.Nodes.JsonObject { ["hostStateRoot"] = Path.Combine(temporary, "host"),
        ["logRoot"] = Path.Combine(temporary, "logs"), ["hostFingerprint"] = new string('a', 64) };
    using (var direct = new DirectScienceGeneration(config))
    {
        var identity = System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllBytes(Path.Combine(generationRoot, "generation.json")))!;
        Check(identity["servicePid"]!.GetValue<int>() == Environment.ProcessId && identity["childPid"] == null &&
            identity["supervisorPid"] == null, "direct-generation-no-invented-child");
        var refused = false;
        try { using var duplicate = new DirectScienceGeneration(config); } catch (IOException) { refused = true; }
        Check(refused, "direct-generation-singleton-lease");
        direct.Returned(2);
        var receipt = System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllBytes(Path.Combine(generationRoot, "completion.json")))!;
        Check(receipt["drainComplete"]!.GetValue<bool>() == false && receipt["cleanupComplete"]!.GetValue<bool>() == false,
            "failure-cannot-fabricate-complete-drain");
        identity = System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllBytes(Path.Combine(generationRoot, "generation.json")))!;
        Check(identity["phase"]!.GetValue<string>() == "RETURNED_PENDING_SERVICE_EXIT", "direct-return-is-not-service-exit");
    }
    File.Delete(Path.Combine(generationRoot, "generation.json"));
    Directory.CreateDirectory(Path.Combine(generationRoot, "generation.json"));
    var failed = false;
    try { using var direct = new DirectScienceGeneration(config); }
    catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { failed = true; }
    Check(failed, "initial-generation-write-failure-preserved");
    using var lease = new FileStream(Path.Combine(generationRoot, "supervisor.lock"), FileMode.Open, FileAccess.ReadWrite, FileShare.None);
    Check(lease.CanWrite, "failed-constructor-releases-lease");
}
finally
{
    if (!temporary.StartsWith(Path.GetFullPath(Path.GetTempPath()) + "MH-014A-Generation-", StringComparison.OrdinalIgnoreCase))
        throw new InvalidDataException("DISPOSABLE_CLEANUP_ROOT_MISMATCH");
    Directory.Delete(temporary, true);
}
Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new { status = "PASS", count = passed.Count, tests = passed,
    writeRestrictedGuardMatrix = "PASS", guardCaseCount = guardCases.Count, guardCases,
    scope = "PURE_DACL_DECLARED_TOKEN_AND_DISPOSABLE_GENERATION_NOT_SCM_PHYSICAL", productionChanges = 0 }));
