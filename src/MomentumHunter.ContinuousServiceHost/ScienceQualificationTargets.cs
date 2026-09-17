using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.Win32.SafeHandles;

namespace MomentumHunter.ContinuousServiceHost;

// Admission and observation only: no service setter, creator, control or cleanup API.
[System.Runtime.Versioning.SupportedOSPlatform("windows")]
internal sealed class ScienceQualificationTargets : IDisposable
{
    internal const string ConfigKey = "qualificationServiceTargets";
    internal const string TaskId = "ARGUS-013B-CLEAN-SUCCESSOR-018A";
    internal const string Profile = "SCIENCE_QUALIFICATION_TARGETS_V1";
    internal static readonly string[] Roles = ["Automation", "ContinuousRuntime", "ContinuousWriter", "Science"];
    private readonly JsonObject declaration;
    private readonly NamedPipeClientStream pipe;
    private readonly SafeProcessHandle ownerProcess;
    private readonly SemaphoreSlim exchange = new(1, 1);
    private readonly string manifestHash, configHash;
    private readonly int ownerPid;
    private readonly long ownerBirth;
    private readonly CancellationTokenSource monitorStop = new();
    private readonly List<JsonObject> observations = [];
    private Task? monitor;
    private Exception? ownerLost;
    private bool disposed;
    internal IReadOnlyList<string> Names { get; }
    internal ScmRestrictedServiceProvenance? RestrictedServiceProvenance { get; private set; }

    private ScienceQualificationTargets(JsonObject declaration, string manifestHash, string configHash,
        NamedPipeClientStream pipe, SafeProcessHandle ownerProcess)
    {
        this.declaration = declaration;
        this.manifestHash = manifestHash;
        this.configHash = configHash;
        this.pipe = pipe;
        this.ownerProcess = ownerProcess;
        ownerPid = declaration["owner"]!["processId"]!.GetValue<int>();
        ownerBirth = declaration["owner"]!["birthFileTimeUtc"]!.GetValue<long>();
        Names = Array.AsReadOnly(Roles.Take(3).Select(role => Service(declaration, role)["name"]!.GetValue<string>()).ToArray());
    }

    internal static bool ValidateOverrideMode(JsonElement config)
    {
        Require(config.ValueKind == JsonValueKind.Object, "CONFIG_OBJECT_REQUIRED");
        var aliases = config.EnumerateObject().Where(p => p.Name.Equals(ConfigKey, StringComparison.OrdinalIgnoreCase)).ToArray();
        if (aliases.Length == 0) return false;
        Require(aliases.Length == 1 && aliases[0].Name == ConfigKey, "OVERRIDE_KEY_AMBIGUOUS");
        UniqueKeys(config);
        var node = JsonNode.Parse(config.GetRawText())!.AsObject();
        Require(node["schemaVersion"]?.GetValue<int>() == 2 &&
            node["inputMode"]?.GetValue<string>() == "OFFLINE_QUALIFICATION", "OVERRIDE_REQUIRES_OFFLINE");
        foreach (var pair in new Dictionary<string, string> {
            ["mode"] = "RESEARCH_ONLY", ["executionAuthority"] = "NONE", ["orderCapability"] = "UNAVAILABLE",
            ["accountReads"] = "UNAVAILABLE", ["positionReads"] = "UNAVAILABLE", ["alpacaPaper"] = "UNAVAILABLE",
            ["alpacaLive"] = "UNAVAILABLE", ["shadowExecution"] = "UNAVAILABLE",
            ["providerAuthority"] = "NONE", ["paperAuthority"] = "NONE", ["liveAuthority"] = "NONE" })
            Require(node[pair.Key]?.GetValue<string>() == pair.Value, "AUTHORITY_NOT_NONE:" + pair.Key);
        var reference = node[ConfigKey] as JsonObject ?? throw Invalid("OVERRIDE_REFERENCE_REQUIRED");
        Exact(reference, "manifest", "sha256");
        Require(reference["manifest"]?.GetValue<string>() == "qualification-targets.json", "MANIFEST_NAME");
        HashText(reference["sha256"]);
        Require(node["offlineInput"] is JsonObject && node["host"] is JsonObject, "OFFLINE_INPUT_REQUIRED");
        foreach (var key in new[] { "credentials", "oauth", "token", "password", "expectedAccountEnding" })
            Require(!node.ContainsKey(key), "CREDENTIAL_INPUT_FORBIDDEN");
        return true;
    }

    internal static ScienceQualificationTargets? Open(ContinuousServiceOptions options, JsonObject config,
        byte[] configBytes, DirectScienceImage image)
    {
        using var document = JsonDocument.Parse(configBytes);
        var requested = ValidateOverrideMode(document.RootElement);
        if (!requested)
        {
            Require(options.QualificationConfigSha256 == null, "REQUEST_DISAPPEARED");
            return null;
        }
        Require(options.Qualification && !options.ConsoleControl && options.Role == "science", "SCM_OFFLINE_ONLY");
        var rawHash = Hash(configBytes);
        Require(rawHash == options.QualificationConfigSha256, "OPTIONS_CONFIG_BYTES_CHANGED");
        var manifestPath = image.Resolve("qualification-targets.json");
        Require(image.Manifest["files"]!.AsArray().Count(f => f!["path"]?.GetValue<string>() == "qualification-targets.json") == 1,
            "MANIFEST_NOT_IN_FROZEN_IMAGE");
        var bytes = File.ReadAllBytes(manifestPath);
        var manifestHash = Hash(bytes);
        Require(manifestHash == config[ConfigKey]!["sha256"]!.GetValue<string>(), "MANIFEST_HASH");
        var value = ValidateDeclaration(config, Parse(bytes), options.ServiceName, options.ConfigPath);
        var owner = value["owner"]!.AsObject();
        foreach (var pair in new[] { ("image", "imageSha256"), ("assembly", "assemblySha256") })
        {
            var relative = owner[pair.Item1]!.GetValue<string>();
            Require(image.Manifest["files"]!.AsArray().Any(f => f!["path"]?.GetValue<string>() == relative), "OWNER_NOT_IN_IMAGE");
            Require(Hash(File.ReadAllBytes(image.Resolve(relative))) == owner[pair.Item2]!.GetValue<string>(), "OWNER_IMAGE_HASH");
        }
        var pipe = new NamedPipeClientStream(".", owner["pipe"]!.GetValue<string>(), PipeDirection.InOut, PipeOptions.Asynchronous);
        SafeProcessHandle? process = null;
        try
        {
            pipe.Connect(3000);
            Require(GetNamedPipeServerProcessId(pipe.SafePipeHandle, out var pid) &&
                pid == owner["processId"]!.GetValue<int>(), "OWNER_PIPE_PID");
            process = OpenProcess(0x1000, false, pid);
            Require(!process.IsInvalid, "OWNER_LIMITED_QUERY_UNAVAILABLE");
            Require(Birth(process) == owner["birthFileTimeUtc"]!.GetValue<long>(), "OWNER_BIRTH");
            var path = new StringBuilder(32768);
            var size = path.Capacity;
            Require(QueryFullProcessImageNameW(process, 0, path, ref size), "OWNER_IMAGE_QUERY");
            Require(LocalPath(path.ToString()) == LocalPath(image.Resolve(owner["image"]!.GetValue<string>())), "OWNER_IMAGE_PATH");
            var result = new ScienceQualificationTargets(value, manifestHash, rawHash, pipe, process);
            try { result.Attest("BEFORE_GUARD"); }
            catch { result.Dispose(); throw; }
            return result;
        }
        catch { process?.Dispose(); pipe.Dispose(); throw; }
    }

    internal static JsonObject ValidateDeclaration(JsonObject config, JsonObject value, string scienceName, string configPath)
    {
        using var document = JsonDocument.Parse(config.ToJsonString());
        Require(ValidateOverrideMode(document.RootElement), "EXPLICIT_REFERENCE_REQUIRED");
        Exact(value, "profile", "taskId", "instanceId", "qualificationRoot", "configurationIdentity",
            "createdAtUtc", "owner", "services");
        Require(value["profile"]?.GetValue<string>() == Profile && value["taskId"]?.GetValue<string>() == TaskId, "TASK_PROFILE");
        var host = config["host"]!.AsObject();
        var instance = value["instanceId"]!.GetValue<string>();
        Require(Regex.IsMatch(instance, @"\Aqual-015-[a-z0-9][a-z0-9-]{0,23}\z") &&
            instance == host["instanceId"]?.GetValue<string>(), "INSTANCE");
        var root = LocalPath(value["qualificationRoot"]!.GetValue<string>());
        Require(root == LocalPath(host["instanceRoot"]!.GetValue<string>()), "ROOT_BINDING");
        foreach (var protectedRoot in new[] { @"C:\ProgramData\MomentumHunter",
            @"C:\Users\steve\OneDrive\Documents\Investing", @"C:\Users\steve\OneDrive\Documents\MomentumHunterData",
            Environment.GetFolderPath(Environment.SpecialFolder.Windows) })
        {
            var boundary = Path.GetFullPath(protectedRoot).TrimEnd('\\').ToUpperInvariant();
            Require(!Overlap(root, boundary), "PRODUCTION_ROOT_OVERLAP");
        }
        for (var parent = new DirectoryInfo(root); parent != null; parent = parent.Parent)
            Require(!File.Exists(Path.Combine(parent.FullName, ".git")) && !Directory.Exists(Path.Combine(parent.FullName, ".git")),
                "CHECKOUT_ROOT_FORBIDDEN");
        var roots = new[] { "installRoot", "runtimeStateRoot", "evidenceRoot", "configRoot", "logRoot", "hostStateRoot" }
            .Select(k => LocalPath(config[k]!.GetValue<string>())).Concat([
                LocalPath(host["science"]!["stateRoot"]!.GetValue<string>()),
                LocalPath(config["researchFactExportV2"]!["exportRoot"]!.GetValue<string>())]).ToArray();
        foreach (var path in roots) Require(Within(path, root), "ISOLATED_ROLE_ROOT");
        for (var i = 0; i < roots.Length; i++)
        for (var j = i + 1; j < roots.Length; j++) Require(!Overlap(roots[i], roots[j]), "ROLE_ROOT_OVERLAP");
        Require(Within(LocalPath(configPath), LocalPath(config["configRoot"]!.GetValue<string>())), "CONFIG_ROOT");
        var keyPath = LexicalPath(config["ipcKeyPath"]!.GetValue<string>());
        Require(Within(keyPath, LocalPath(config["configRoot"]!.GetValue<string>())) &&
            LocalPath(configPath) != keyPath, "CONFIG_KEY_ALIAS");
        Require(value["configurationIdentity"]?.GetValue<string>() == ConfigurationIdentity(config), "CONFIGURATION_IDENTITY");
        var created = Utc(value["createdAtUtc"]);
        Require(created <= DateTimeOffset.UtcNow, "FUTURE_MANIFEST");
        var owner = value["owner"]!.AsObject();
        Exact(owner, "epoch", "processId", "birthFileTimeUtc", "image", "imageSha256", "assembly", "assemblySha256", "pipe");
        var epoch = Id(owner["epoch"]);
        Require(owner["processId"]!.GetValue<int>() > 0 && owner["birthFileTimeUtc"]!.GetValue<long>() > 0, "OWNER_IDENTITY");
        Require(owner["pipe"]?.GetValue<string>() == "Argus015-" + epoch, "OWNER_PIPE_NAME");
        HashText(owner["imageSha256"]); HashText(owner["assemblySha256"]);
        var ownerStarted = DateTimeOffset.FromFileTime(owner["birthFileTimeUtc"]!.GetValue<long>());
        Require(ownerStarted <= created, "OWNER_CREATION_CHRONOLOGY");
        var services = value["services"]!.AsArray();
        Require(services.Count == 4, "EXACT_FOUR_ROLES");
        var seenRoles = new HashSet<string>(StringComparer.Ordinal);
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var receipts = new HashSet<string>(StringComparer.Ordinal);
        foreach (var entry in services)
        {
            var service = entry!.AsObject();
            Exact(service, "role", "name", "sid", "receiptId", "creatorEpoch", "creationApi", "created",
                "creationTimeUtc", "initialStartMode", "initialState", "configurationSha256", "securityPolicy");
            var role = service["role"]!.GetValue<string>();
            var name = service["name"]!.GetValue<string>();
            Require(Roles.Contains(role, StringComparer.Ordinal) && seenRoles.Add(role), "ROLE_DUPLICATE_OR_UNKNOWN");
            var suffix = role.StartsWith("Continuous", StringComparison.Ordinal) ? role["Continuous".Length..] : role;
            var expected = "MomentumHunterContinuous-" + instance + "-" + suffix;
            Require(name == expected && names.Add(name) &&
                !ScienceServiceDaclPolicy.Targets.Contains(name, StringComparer.OrdinalIgnoreCase) &&
                !name.Equals("MomentumHunterContinuousScience", StringComparison.OrdinalIgnoreCase), "NONDISPOSABLE_TARGET");
            if (role != "Automation")
                Require(name == host["services"]![suffix.ToLowerInvariant()]?.GetValue<string>(), "HOST_ROLE_BINDING");
            if (role == "Science") Require(name == scienceName, "SELF_SCIENCE_BINDING");
            Require(service["sid"]?.GetValue<string>() == ServiceSid(name), "SERVICE_SID");
            Require(receipts.Add(Id(service["receiptId"])) && service["creatorEpoch"]?.GetValue<string>() == epoch,
                "RECEIPT_IDENTITY");
            Require(service["creationApi"]?.GetValue<string>() == "CreateServiceW" &&
                service["created"]?.GetValue<bool>() == true &&
                service["initialStartMode"]?.GetValue<string>() == "DISABLED" &&
                service["initialState"]?.GetValue<string>() == "STOPPED", "NOT_OWNED_DISABLED_CREATION");
            var when = Utc(service["creationTimeUtc"]);
            Require(when >= ownerStarted && when <= created, "CREATION_CHRONOLOGY");
            HashText(service["configurationSha256"]);
            var policy = service["securityPolicy"]!.AsObject();
            Exact(policy, "sddl", "daclSha256");
            var sd = new RawSecurityDescriptor(policy["sddl"]!.GetValue<string>());
            Require(sd.Owner != null && sd.Group != null && sd.DiscretionaryAcl != null, "INCOMPLETE_SECURITY_POLICY");
            var acl = new byte[sd.DiscretionaryAcl!.BinaryLength];
            sd.DiscretionaryAcl.GetBinaryForm(acl, 0);
            Require(Hash(acl) == HashText(policy["daclSha256"]), "DACL_IDENTITY");
        }
        return (JsonObject)value.DeepClone();
    }

    internal void Attest(string stage) => AttestAsync(stage, CancellationToken.None).GetAwaiter().GetResult();

    private async Task AttestAsync(string stage, CancellationToken cancellation)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromSeconds(3));
        await exchange.WaitAsync(timeout.Token);
        try
        {
            Require(!disposed && GetNamedPipeServerProcessId(pipe.SafePipeHandle, out var pid) && pid == ownerPid &&
                Birth(ownerProcess) == ownerBirth && GetExitCodeProcess(ownerProcess, out var exit) && exit == 259, "OWNER_EPOCH_LOST");
            var challenge = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
            var request = new JsonObject { ["profile"] = "SCIENCE_TARGET_OWNER_REQUEST_V1", ["challenge"] = challenge,
                ["manifestSha256"] = manifestHash, ["configSha256"] = configHash, ["stage"] = stage };
            var bytes = Encoding.UTF8.GetBytes(request.ToJsonString());
            await pipe.WriteAsync(BitConverter.GetBytes(bytes.Length), timeout.Token);
            await pipe.WriteAsync(bytes, timeout.Token); await pipe.FlushAsync(timeout.Token);
            var header = new byte[4];
            await pipe.ReadExactlyAsync(header, timeout.Token);
            var size = BitConverter.ToInt32(header);
            Require(size > 0 && size <= 65536, "OWNER_RESPONSE_BOUND");
            var output = new byte[size];
            await pipe.ReadExactlyAsync(output, timeout.Token);
            var response = Parse(output);
            ValidateOwnerResponse(declaration, response, manifestHash, configHash, challenge, stage);
            if (stage == "BEFORE_GUARD")
            {
                var science = Service(declaration, "Science");
                var row = Service(response, "Science");
                RestrictedServiceProvenance = new(science["name"]!.GetValue<string>(),
                    science["sid"]!.GetValue<string>(), row["serviceSidType"]!.GetValue<int>(), (uint)Environment.ProcessId);
            }
            lock (observations) observations.Add(new JsonObject { ["stage"] = stage, ["atUtc"] = DateTimeOffset.UtcNow.ToString("O"),
                ["responseSha256"] = Hash(output), ["ownerEpoch"] = declaration["owner"]!["epoch"]!.DeepClone() });
        }
        finally { exchange.Release(); }
    }

    internal static void ValidateOwnerResponse(JsonObject declaration, JsonObject response,
        string manifestHash, string configHash, string challenge, string stage)
    {
        Exact(response, "profile", "taskId", "epoch", "challenge", "manifestSha256", "configSha256",
            "stage", "hostAdmission", "services");
        Require(response["profile"]?.GetValue<string>() == "SCIENCE_TARGET_OWNER_RESPONSE_V1" &&
            response["taskId"]?.GetValue<string>() == TaskId &&
            response["epoch"]?.GetValue<string>() == declaration["owner"]!["epoch"]!.GetValue<string>() &&
            response["challenge"]?.GetValue<string>() == challenge &&
            response["manifestSha256"]?.GetValue<string>() == manifestHash &&
            response["configSha256"]?.GetValue<string>() == configHash &&
            response["stage"]?.GetValue<string>() == stage, "OWNER_ATTESTATION_BINDING");
        var admission = response["hostAdmission"]!.AsObject();
        Exact(admission, "configurationValidated", "rootSecurityValidated", "clientProcessValidated", "imageValidated",
            "preActivationPassed", "providerContact", "creationHandlesRetained");
        foreach (var key in admission.Select(p => p.Key))
            Require(admission[key]?.GetValue<bool>() == (key != "providerContact"), "OWNER_ADMISSION:" + key);
        Require(response["services"]!.AsArray().Count == 4, "OWNER_ROLE_COUNT");
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var node in response["services"]!.AsArray())
        {
            var row = node!.AsObject();
            var role = row["role"]!.GetValue<string>();
            var keys = new[] { "role", "name", "receiptId", "configurationSha256", "daclSha256", "ownedCreationHandleRetained", "pendingDelete" };
            Exact(row, role == "Science" ? [.. keys, "serviceSidType"] : keys);
            if (role == "Science") Require(row["serviceSidType"]?.GetValue<int>() == 3, "OWNER_SCIENCE_SID_TYPE_NOT_RESTRICTED");
            Require(Roles.Contains(role, StringComparer.Ordinal) && seen.Add(role), "OWNER_ROLE_DUPLICATE");
            var expected = Service(declaration, role);
            foreach (var key in new[] { "name", "receiptId", "configurationSha256" })
                Require(row[key]?.GetValue<string>() == expected[key]!.GetValue<string>(), "OWNER_OBJECT:" + key);
            Require(row["daclSha256"]?.GetValue<string>() == expected["securityPolicy"]!["daclSha256"]!.GetValue<string>() &&
                row["ownedCreationHandleRetained"]?.GetValue<bool>() == true &&
                row["pendingDelete"]?.GetValue<bool>() == false, "OWNER_OBJECT_LIFETIME");
        }
    }

    internal void StartMonitoring(Action cancelGeneration)
    {
        Require(monitor == null, "DUPLICATE_OWNER_MONITOR");
        monitor = Task.Run(async () =>
        {
            try
            {
                await MonitorAsync(() => AttestAsync("GENERATION_ACTIVE", CancellationToken.None), monitorStop.Token);
            }
            catch (OperationCanceledException) when (monitorStop.IsCancellationRequested) { }
            catch (Exception ex) { ownerLost = ex; cancelGeneration(); }
        });
    }

    // Stop between exchanges: cancelling a framed read would poison the final attestation.
    internal static async Task MonitorAsync(Func<Task> attest, CancellationToken stop)
    {
        while (true)
        {
            await Task.Delay(1000, stop);
            stop.ThrowIfCancellationRequested();
            await attest();
        }
    }

    internal void FinishMonitoring()
    {
        monitorStop.Cancel();
        monitor?.GetAwaiter().GetResult();
        if (ownerLost != null) throw new InvalidDataException("QUALIFICATION_OWNER_LOST", ownerLost);
    }

    internal JsonObject Evidence()
    {
        lock (observations) return new JsonObject { ["scope"] = "ISOLATED_REPLICA_TARGETS_ONLY",
            ["manifestSha256"] = manifestHash, ["configSha256"] = configHash,
            ["productionIsolation"] = "UNPROVEN_PENDING_CONTROLLED_PRODUCTION_RECREATION",
            ["names"] = new JsonArray(Names.Select(n => JsonValue.Create(n)).ToArray()),
            ["observations"] = new JsonArray(observations.Select(o => o.DeepClone()).ToArray()) };
    }

    internal static string ConfigurationIdentity(JsonObject config)
    {
        var copy = (JsonObject)config.DeepClone();
        copy.Remove("hostFingerprint");
        copy["host"]!["science"]!.AsObject().Remove("imageManifestSha256");
        copy[ConfigKey]!.AsObject().Remove("sha256");
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream)) Canonical(writer, copy);
        return Hash(stream.ToArray());
    }
    private static void Canonical(Utf8JsonWriter writer, JsonNode? value)
    {
        if (value is JsonObject obj) { writer.WriteStartObject(); foreach (var pair in obj.OrderBy(p => p.Key, StringComparer.Ordinal)) { writer.WritePropertyName(pair.Key); Canonical(writer, pair.Value); } writer.WriteEndObject(); }
        else if (value is JsonArray array) { writer.WriteStartArray(); foreach (var item in array) Canonical(writer, item); writer.WriteEndArray(); }
        else if (value == null) writer.WriteNullValue();
        else value.WriteTo(writer);
    }
    internal static JsonObject Parse(byte[] bytes)
    {
        Require(bytes.Length <= 131072, "JSON_SIZE_BOUND");
        using var document = JsonDocument.Parse(bytes, new JsonDocumentOptions { MaxDepth = 32 });
        UniqueKeys(document.RootElement);
        return JsonNode.Parse(bytes)!.AsObject();
    }
    private static void UniqueKeys(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var property in value.EnumerateObject()) { Require(names.Add(property.Name), "DUPLICATE_JSON_KEY"); UniqueKeys(property.Value); }
        }
        else if (value.ValueKind == JsonValueKind.Array) foreach (var item in value.EnumerateArray()) UniqueKeys(item);
    }
    private static JsonObject Service(JsonObject value, string role) =>
        value["services"]!.AsArray().Single(n => n!["role"]!.GetValue<string>() == role)!.AsObject();
    private static void Exact(JsonObject value, params string[] keys) =>
        Require(value.Count == keys.Length && keys.All(value.ContainsKey), "EXACT_DESCRIPTOR_REQUIRED");
    internal static string ServiceSid(string name)
    {
        var hash = SHA1.HashData(Encoding.Unicode.GetBytes(name.ToUpperInvariant()));
        return "S-1-5-80-" + string.Join("-", Enumerable.Range(0, 5).Select(i => BitConverter.ToUInt32(hash, i * 4)));
    }
    internal static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    private static string HashText(JsonNode? value)
    {
        var text = value?.GetValue<string>();
        Require(text != null && Regex.IsMatch(text, @"\A[0-9a-f]{64}\z"), "SHA256_REQUIRED");
        return text!;
    }
    private static string Id(JsonNode? value)
    {
        var text = value?.GetValue<string>();
        Require(text != null && Regex.IsMatch(text, @"\A[0-9a-f]{32}\z"), "RECEIPT_EPOCH_ID");
        return text!;
    }
    private static DateTimeOffset Utc(JsonNode? value)
    {
        Require(DateTimeOffset.TryParseExact(value?.GetValue<string>(), "O", CultureInfo.InvariantCulture,
            DateTimeStyles.None, out var when) && when.Offset == TimeSpan.Zero, "UTC_TIMESTAMP_REQUIRED");
        return when;
    }
    internal static string LocalPath(string path)
    {
        var full = LexicalPath(path);
        for (FileSystemInfo? item = new FileInfo(full); item != null; item = Directory.GetParent(item.FullName))
            Require((item.Attributes & FileAttributes.ReparsePoint) == 0, "REPARSE_PATH");
        using var handle = CreateFileW(full, 0x80, 7, 0, 3, 0x02200000, 0);
        Require(!handle.IsInvalid, "PATH_IDENTITY_UNAVAILABLE");
        var final = new StringBuilder(32768);
        var length = GetFinalPathNameByHandleW(handle, final, final.Capacity, 0);
        Require(length > 0 && length < final.Capacity && final.ToString().StartsWith(@"\\?\", StringComparison.Ordinal) &&
            final.ToString()[4..].TrimEnd('\\').Equals(full, StringComparison.OrdinalIgnoreCase), "PATH_ALIAS");
        Require(GetFileInformationByHandle(handle, out var info), "PATH_INFORMATION");
        Require((info.Attributes & 16) != 0 || info.Links == 1, "HARDLINK_FILE_FORBIDDEN");
        return full;
    }
    private static string LexicalPath(string path)
    {
        Require(Path.IsPathFullyQualified(path) && !path.StartsWith(@"\\", StringComparison.Ordinal) &&
            !path[2..].Contains(':') && path.All(c => c >= 32 && c < 127), "LOCAL_PATH_REQUIRED");
        var full = Path.GetFullPath(path).TrimEnd('\\');
        Require(path.Replace('/', '\\').TrimEnd('\\').Equals(full, StringComparison.OrdinalIgnoreCase), "NONCANONICAL_PATH");
        foreach (var part in full[3..].Split('\\'))
            Require(part.Length > 0 && !part.EndsWith('.') && !part.EndsWith(' ') &&
                !Regex.IsMatch(part, @"\A(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\z", RegexOptions.IgnoreCase), "AMBIGUOUS_PATH");
        return full.ToUpperInvariant();
    }
    private static bool Within(string path, string root) => path.StartsWith(root + "\\", StringComparison.OrdinalIgnoreCase);
    private static bool Overlap(string first, string second) => first == second || Within(first, second) || Within(second, first);
    private static long Birth(SafeProcessHandle process)
    {
        Require(GetProcessTimes(process, out var created, out _, out _, out _), "OWNER_PROCESS_TIMES");
        return created;
    }
    private static InvalidDataException Invalid(string code) => new("QUALIFICATION_TARGET_" + code);
    private static void Require(bool condition, string code) { if (!condition) throw Invalid(code); }
    public void Dispose()
    {
        if (disposed) return;
        monitorStop.Cancel();
        try { monitor?.GetAwaiter().GetResult(); }
        finally { disposed = true; pipe.Dispose(); ownerProcess.Dispose(); monitorStop.Dispose(); exchange.Dispose(); }
    }
    [StructLayout(LayoutKind.Sequential)] private struct FileInformation
    { public uint Attributes, CreatedLow, CreatedHigh, AccessedLow, AccessedHigh, WrittenLow, WrittenHigh,
        Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow; }
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetNamedPipeServerProcessId(SafePipeHandle pipe, out uint pid);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern SafeProcessHandle OpenProcess(uint access, bool inherit, uint pid);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetProcessTimes(SafeProcessHandle process, out long created, out long exited, out long kernel, out long user);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetExitCodeProcess(SafeProcessHandle process, out uint exit);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool QueryFullProcessImageNameW(SafeProcessHandle process, uint flags, StringBuilder path, ref int size);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern SafeFileHandle CreateFileW(string path, uint access, uint share, nint security, uint disposition, uint flags, nint template);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern uint GetFinalPathNameByHandleW(SafeFileHandle file, StringBuilder path, int size, uint flags);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetFileInformationByHandle(SafeFileHandle file, out FileInformation information);
}
