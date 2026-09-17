using System.Diagnostics;
using System.Security.AccessControl;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using MomentumHunter.ContinuousServiceHost;

var passed = new List<string>();
void Check(bool value, string label) { if (!value) throw new Exception(label); passed.Add(label); }
void Reject(Action action, string label)
{
    try { action(); }
    catch (Exception ex) when (ex is InvalidDataException or ArgumentException or InvalidOperationException or JsonException or IOException)
    { passed.Add(label); return; }
    throw new Exception("NOT_REJECTED:" + label);
}
bool Mode(JsonObject value)
{
    using var document = JsonDocument.Parse(value.ToJsonString());
    return ScienceQualificationTargets.ValidateOverrideMode(document.RootElement);
}
var temporary = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "MH-015-Targets-" + Guid.NewGuid().ToString("N")));
Directory.CreateDirectory(temporary);
try
{
    const string instance = "qual-015-unit";
    const string scienceName = "MomentumHunterContinuous-qual-015-unit-Science";
    var hostNames = new JsonObject { ["runtime"] = "MomentumHunterContinuous-qual-015-unit-Runtime",
        ["writer"] = "MomentumHunterContinuous-qual-015-unit-Writer", ["science"] = scienceName };
    var config = new JsonObject { ["schemaVersion"] = 2, ["inputMode"] = "OFFLINE_QUALIFICATION",
        ["mode"] = "RESEARCH_ONLY", ["executionAuthority"] = "NONE", ["orderCapability"] = "UNAVAILABLE",
        ["accountReads"] = "UNAVAILABLE", ["positionReads"] = "UNAVAILABLE", ["alpacaPaper"] = "UNAVAILABLE",
        ["alpacaLive"] = "UNAVAILABLE", ["shadowExecution"] = "UNAVAILABLE", ["providerAuthority"] = "NONE",
        ["paperAuthority"] = "NONE", ["liveAuthority"] = "NONE", ["hostFingerprint"] = new string('a', 64),
        ["offlineInput"] = new JsonObject { ["fixture"] = "DECLARED_SYNTHETIC_NO_PROVIDER" },
        ["qualificationServiceTargets"] = new JsonObject { ["manifest"] = "qualification-targets.json", ["sha256"] = new string('b', 64) },
        ["host"] = new JsonObject { ["instanceId"] = instance, ["instanceRoot"] = temporary, ["services"] = hostNames,
            ["shutdownSeconds"] = 30, ["science"] = new JsonObject { ["enabled"] = true, ["stateRoot"] = Path.Combine(temporary, "science"),
                ["imageManifestSha256"] = new string('c', 64) } },
        ["researchFactExportV2"] = new JsonObject { ["exportRoot"] = Path.Combine(temporary, "export") } };
    foreach (var key in new[] { "installRoot", "runtimeStateRoot", "evidenceRoot", "configRoot", "logRoot", "hostStateRoot" })
        config[key] = Path.Combine(temporary, key);
    foreach (var path in new[] { "installRoot", "runtimeStateRoot", "evidenceRoot", "configRoot", "logRoot", "hostStateRoot" }
        .Select(k => config[k]!.GetValue<string>()).Concat([Path.Combine(temporary, "science"), Path.Combine(temporary, "export")]))
        Directory.CreateDirectory(path);
    var configPath = Path.Combine(config["configRoot"]!.GetValue<string>(), "config.json");
    config["ipcKeyPath"] = Path.Combine(config["configRoot"]!.GetValue<string>(), "writer.key");
    File.WriteAllText(config["ipcKeyPath"]!.GetValue<string>(), "TEST_ONLY_NOT_A_CREDENTIAL");
    void SaveConfig(JsonObject value) => File.WriteAllText(configPath, value.ToJsonString());
    ContinuousServiceOptions Options(JsonObject value, string role, string inst)
    {
        SaveConfig(value);
        return ContinuousServiceOptions.Create(["--role", role, "--repository-root", temporary,
            "--python-executable", "python.exe", "--config", configPath, "--instance", inst]);
    }
    SaveConfig(config);
    Check(Mode(config), "offline-reference-admission");
    var options = Options(config, "science", instance);
    Check(options.Qualification && options.ServiceName == scienceName &&
        options.QualificationConfigSha256 == ScienceQualificationTargets.Hash(File.ReadAllBytes(configPath)), "options-bind-exact-config-bytes");
    var legacy = new JsonObject { ["schemaVersion"] = 1 };
    Check(!Mode(legacy), "legacy-no-override");
    Check(Options(legacy, "runtime", "production").ServiceName == "MomentumHunterContinuousRuntime", "legacy-production-name-unchanged");
    var production = (JsonObject)config.DeepClone();
    production.Remove("qualificationServiceTargets");
    production["inputMode"] = "LIVE_PRODUCTION";
    production["host"]!["instanceId"] = "production";
    production["host"]!["services"] = new JsonObject { ["runtime"] = "MomentumHunterContinuousRuntime",
        ["writer"] = "MomentumHunterContinuousWriter", ["science"] = "MomentumHunterContinuousScience" };
    Check(!Mode(production), "versioned-production-no-override");
    Check(!Options(production, "runtime", "production").Qualification, "versioned-production-options-unchanged");
    foreach (var baseline in new[] { legacy, production })
    foreach (var replacement in new JsonNode?[] { null, new JsonObject(), config["qualificationServiceTargets"]!.DeepClone() })
    {
        var invalid = (JsonObject)baseline.DeepClone();
        invalid["qualificationServiceTargets"] = replacement?.DeepClone();
        Reject(() => Options(invalid, "runtime", "production"), "production-any-override-" + passed.Count);
    }
    foreach (var mode in new JsonNode?[] { null, JsonValue.Create("LIVE_PRODUCTION"), JsonValue.Create("OFFLINE"), JsonValue.Create(true), JsonValue.Create(2) })
    {
        var invalid = (JsonObject)config.DeepClone(); invalid["inputMode"] = mode?.DeepClone();
        Reject(() => Mode(invalid), "wrong-mode-" + passed.Count);
    }
    foreach (var key in new[] { "providerAuthority", "paperAuthority", "liveAuthority", "executionAuthority",
        "orderCapability", "accountReads", "positionReads", "alpacaPaper", "alpacaLive", "shadowExecution" })
    {
        var invalid = (JsonObject)config.DeepClone(); invalid[key] = "AVAILABLE";
        Reject(() => Mode(invalid), "authority-" + key);
        invalid.Remove(key);
        Reject(() => Mode(invalid), "missing-authority-" + key);
    }
    foreach (var key in new[] { "credentials", "oauth", "token", "password", "expectedAccountEnding" })
    {
        var invalid = (JsonObject)config.DeepClone(); invalid[key] = "SYNTHETIC";
        Reject(() => Mode(invalid), "credential-input-" + key);
    }
    Reject(() => ScienceQualificationTargets.Parse(Encoding.UTF8.GetBytes("{\"a\":1,\"A\":2}")), "duplicate-case-json");
    Reject(() => ScienceQualificationTargets.Parse(Encoding.UTF8.GetBytes("{\"a\":{\"x\":1,\"x\":2}}")), "nested-duplicate-json");
    var alias = (JsonObject)config.DeepClone();
    alias["QualificationServiceTargets"] = alias["qualificationServiceTargets"]!.DeepClone();
    Reject(() => Mode(alias), "override-key-alias");
    SaveConfig(config);
    var process = Process.GetCurrentProcess();
    var epoch = Guid.NewGuid().ToString("N");
    var created = DateTimeOffset.UtcNow.ToString("O");
    var sddl = "O:SYG:SYD:(A;;GA;;;SY)(A;;GA;;;BA)";
    var acl = new RawSecurityDescriptor(sddl).DiscretionaryAcl!;
    var aclBytes = new byte[acl.BinaryLength]; acl.GetBinaryForm(aclBytes, 0);
    var declaration = new JsonObject { ["profile"] = ScienceQualificationTargets.Profile,
        ["taskId"] = ScienceQualificationTargets.TaskId, ["instanceId"] = instance, ["qualificationRoot"] = temporary,
        ["configurationIdentity"] = ScienceQualificationTargets.ConfigurationIdentity(config), ["createdAtUtc"] = created,
        ["owner"] = new JsonObject { ["epoch"] = epoch, ["processId"] = process.Id,
            ["birthFileTimeUtc"] = process.StartTime.ToUniversalTime().ToFileTimeUtc(),
            ["image"] = "owner/Owner.exe", ["imageSha256"] = new string('d', 64),
            ["assembly"] = "owner/Owner.dll", ["assemblySha256"] = new string('e', 64), ["pipe"] = "Argus015-" + epoch },
        ["services"] = new JsonArray() };
    foreach (var role in ScienceQualificationTargets.Roles)
    {
        var suffix = role.StartsWith("Continuous", StringComparison.Ordinal) ? role["Continuous".Length..] : role;
        var name = "MomentumHunterContinuous-" + instance + "-" + suffix;
        declaration["services"]!.AsArray().Add(new JsonObject { ["role"] = role, ["name"] = name,
            ["sid"] = ScienceQualificationTargets.ServiceSid(name), ["receiptId"] = Guid.NewGuid().ToString("N"),
            ["creatorEpoch"] = epoch, ["creationApi"] = "CreateServiceW", ["created"] = true,
            ["creationTimeUtc"] = created, ["initialStartMode"] = "DISABLED", ["initialState"] = "STOPPED",
            ["configurationSha256"] = new string('f', 64),
            ["securityPolicy"] = new JsonObject { ["sddl"] = sddl, ["daclSha256"] = ScienceQualificationTargets.Hash(aclBytes) } });
    }
    JsonObject Admit(JsonObject value, JsonObject? cfg = null) => ScienceQualificationTargets.ValidateDeclaration(cfg ?? config, value, scienceName, configPath);
    Check(Admit(declaration)["services"]!.AsArray().Count == 4, "synthetic-four-role-declaration-valid-not-native-ownership");
    var retiredOwner = (JsonObject)declaration.DeepClone();
    retiredOwner["taskId"] = "ARGUS-013B-SECURE-BEFORE-ACTIVATE-SERVICE-RECREATION-015";
    Reject(() => Admit(retiredOwner), "retired-lineage-owner-is-not-successor-authority");
    foreach (var field in declaration.Select(p => p.Key).ToArray())
    {
        var invalid = (JsonObject)declaration.DeepClone(); invalid.Remove(field);
        Reject(() => Admit(invalid), "missing-manifest-field-" + field);
    }
    foreach (var field in declaration["owner"]!.AsObject().Select(p => p.Key).ToArray())
    {
        var invalid = (JsonObject)declaration.DeepClone(); invalid["owner"]!.AsObject().Remove(field);
        Reject(() => Admit(invalid), "missing-owner-field-" + field);
    }
    foreach (var mutation in new Action<JsonObject>[] {
        v => v["taskId"] = "OTHER", v => v["profile"] = "OTHER", v => v["instanceId"] = "production",
        v => v["configurationIdentity"] = new string('0',64), v => v["extra"] = true,
        v => v["qualificationRoot"] = temporary + "sibling", v => v["owner"]!["pipe"] = "other",
        v => v["owner"]!["processId"] = 0, v => v["owner"]!["birthFileTimeUtc"] = 0,
        v => v["services"]!.AsArray().RemoveAt(0),
        v => v["services"]![0]!["name"] = "MomentumHunterAutomation",
        v => v["services"]![0]!["name"] = "UnknownUnownedService",
        v => v["services"]![0]!["name"] = v["services"]![1]!["name"]!.DeepClone(),
        v => v["services"]![0]!["name"] = v["services"]![0]!["name"]!.GetValue<string>() + "\n",
        v => v["services"]![0]!["created"] = false, v => v["services"]![0]!["creationApi"] = "OpenServiceW",
        v => v["services"]![0]!["initialStartMode"] = "AUTO", v => v["services"]![0]!["initialState"] = "RUNNING",
        v => v["services"]![0]!["creatorEpoch"] = new string('0',32),
        v => v["services"]![0]!["receiptId"] = v["services"]![1]!["receiptId"]!.DeepClone(),
        v => v["services"]![0]!["sid"] = "S-1-5-18",
        v => v["services"]![0]!["securityPolicy"]!["daclSha256"] = new string('0',64),
        v => v["services"]![0]!["securityPolicy"]!["sddl"] = "O:SYG:SY",
        v => v["services"]![0]!["role"] = "WRITER"
    })
    {
        var invalid = (JsonObject)declaration.DeepClone(); mutation(invalid);
        Reject(() => Admit(invalid), "declaration-negative-" + passed.Count);
    }
    foreach (var key in new[] { "installRoot", "runtimeStateRoot", "evidenceRoot", "configRoot", "logRoot", "hostStateRoot" })
    {
        var invalid = (JsonObject)config.DeepClone(); invalid[key] = temporary;
        Reject(() => Admit(declaration, invalid), "role-root-" + key);
    }
    var identity = ScienceQualificationTargets.ConfigurationIdentity(config);
    var knotOnly = (JsonObject)config.DeepClone();
    knotOnly["hostFingerprint"] = new string('0',64); knotOnly["host"]!["science"]!["imageManifestSha256"] = new string('1',64);
    knotOnly["qualificationServiceTargets"]!["sha256"] = new string('2',64);
    Check(ScienceQualificationTargets.ConfigurationIdentity(knotOnly) == identity, "declared-nonrecursive-hash-domain");
    knotOnly["host"]!["shutdownSeconds"] = 31;
    Check(ScienceQualificationTargets.ConfigurationIdentity(knotOnly) != identity, "other-config-byte-affects-projection");
    foreach (var path in new[] { temporary + "\\..\\" + Path.GetFileName(temporary), temporary + ".", temporary + " ",
        temporary + ":stream", "\\\\localhost\\c$\\Temp", "C:relative" })
        Reject(() => ScienceQualificationTargets.LocalPath(path), "path-alias-" + passed.Count);
    var response = new JsonObject { ["profile"] = "SCIENCE_TARGET_OWNER_RESPONSE_V1", ["taskId"] = ScienceQualificationTargets.TaskId,
        ["epoch"] = epoch, ["challenge"] = new string('a',64), ["manifestSha256"] = new string('b',64),
        ["configSha256"] = new string('c',64), ["stage"] = "BEFORE_GUARD",
        ["hostAdmission"] = new JsonObject { ["configurationValidated"] = true, ["rootSecurityValidated"] = true,
            ["clientProcessValidated"] = true, ["imageValidated"] = true, ["preActivationPassed"] = true,
            ["providerContact"] = false, ["creationHandlesRetained"] = true }, ["services"] = new JsonArray() };
    foreach (var node in declaration["services"]!.AsArray())
    {
        var value = node!.AsObject();
        var row = new JsonObject { ["role"] = value["role"]!.DeepClone(),
            ["name"] = value["name"]!.DeepClone(), ["receiptId"] = value["receiptId"]!.DeepClone(),
            ["configurationSha256"] = value["configurationSha256"]!.DeepClone(),
            ["daclSha256"] = value["securityPolicy"]!["daclSha256"]!.DeepClone(),
            ["ownedCreationHandleRetained"] = true, ["pendingDelete"] = false };
        if (value["role"]!.GetValue<string>() == "Science") row["serviceSidType"] = 3;
        response["services"]!.AsArray().Add(row);
    }
    void Response(JsonObject value) => ScienceQualificationTargets.ValidateOwnerResponse(declaration, value,
        new string('b',64), new string('c',64), new string('a',64), "BEFORE_GUARD");
    Response(response); passed.Add("synthetic-owner-response-contract-not-native-proof");
    foreach (var sidType in new[] { 0, 1, 2, 4, -1 })
    {
        var invalid = (JsonObject)response.DeepClone();
        invalid["services"]!.AsArray().Single(s => s!["role"]!.GetValue<string>() == "Science")!["serviceSidType"] = sidType;
        Reject(() => Response(invalid), "015C-owner-nonrestricted-SID-type-" + sidType);
    }
    {
        var invalid = (JsonObject)response.DeepClone();
        invalid["services"]!.AsArray().Single(s => s!["role"]!.GetValue<string>() == "Science")!.AsObject().Remove("serviceSidType");
        Reject(() => Response(invalid), "015C-old-response-without-SID-type-fails-closed");
    }
    {
        var invalid = (JsonObject)response.DeepClone();
        invalid["services"]![0]!["serviceSidType"] = 3;
        Reject(() => Response(invalid), "015C-SID-type-cannot-be-moved-to-other-role");
    }
    foreach (var key in new[] { "profile", "taskId", "epoch", "challenge", "manifestSha256", "configSha256", "stage" })
    {
        var invalid = (JsonObject)response.DeepClone(); invalid[key] = "OTHER";
        Reject(() => Response(invalid), "owner-response-" + key);
    }
    foreach (var key in response["hostAdmission"]!.AsObject().Select(p => p.Key))
    {
        var invalid = (JsonObject)response.DeepClone(); invalid["hostAdmission"]![key] = key == "providerContact";
        Reject(() => Response(invalid), "owner-admission-" + key);
    }
    foreach (var mutation in new Action<JsonObject>[] {
        v => v["services"]![0]!["receiptId"] = new string('0',32),
        v => v["services"]![0]!["ownedCreationHandleRetained"] = false,
        v => v["services"]![0]!["pendingDelete"] = true,
        v => v["services"]![0]!["configurationSha256"] = new string('0',64),
        v => v["services"]![0]!["daclSha256"] = new string('0',64),
        v => v["services"]![0]!["name"] = "SAME_NAME_REPLACEMENT",
        v => v["services"]![0]!["role"] = v["services"]![1]!["role"]!.DeepClone(),
        v => v["services"]!.AsArray().RemoveAt(0)
    })
    {
        var invalid = (JsonObject)response.DeepClone(); mutation(invalid);
        Reject(() => Response(invalid), "owner-lifetime-negative-" + passed.Count);
    }
    Check(ScienceServiceDaclPolicy.Targets.SequenceEqual(new[] {
        "MomentumHunterAutomation", "MomentumHunterContinuousRuntime", "MomentumHunterContinuousWriter" }),
        "production-target-array-unchanged");
    using (var stop = new CancellationTokenSource())
    {
        var began = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var complete = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var exchanges = 0;
        var monitoring = ScienceQualificationTargets.MonitorAsync(async () => {
            exchanges++; began.SetResult(); await complete.Task;
        }, stop.Token);
        await began.Task.WaitAsync(TimeSpan.FromSeconds(3));
        stop.Cancel();
        Check(!monitoring.IsCompleted, "monitor-stop-waits-in-flight-frame");
        complete.SetResult();
        try { await monitoring.WaitAsync(TimeSpan.FromSeconds(3)); }
        catch (OperationCanceledException) { }
        Check(exchanges == 1 && monitoring.IsCanceled, "monitor-no-next-exchange-after-stop");
    }
    Console.WriteLine(JsonSerializer.Serialize(new { status = "PASS", count = passed.Count, tests = passed,
        scope = "ACTUAL_SOURCE_OPTIONS_DECLARATION_RESPONSE_CONTRACT_AND_LOCAL_PATHS_NOT_NATIVE_SERVICE_OWNERSHIP",
        servicesCreated = 0, providerContact = false, productionChanged = false }));
}
finally
{
    var prefix = Path.GetFullPath(Path.GetTempPath()) + "MH-015-Targets-";
    if (!temporary.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("TEST_CLEANUP_SCOPE");
    Directory.Delete(temporary, true);
}
