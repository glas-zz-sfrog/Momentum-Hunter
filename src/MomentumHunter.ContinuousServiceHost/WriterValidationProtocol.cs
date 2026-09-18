using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace MomentumHunter.ContinuousServiceHost;

// This checks the pinned validator's protocol, not a substitute token/admission policy.
internal sealed class WriterValidationProtocol
{
    private const string Profile = "bounded-existing-scm-writer-v1";
    private const string StageMarker = "WRITER_ASSUMPTION_016J=";
    private const string ReportMarker = "WRITER_SELF_AUTHORITY_016J=";
    private static readonly UTF8Encoding Utf8 = new(false, true);
    private static readonly int[] ServiceRights = [2, 16, 32, 64, 256, 65536, 262144, 524288];
    private static readonly string[] ReplicaNames = ["unrelated_host", "unrelated_repository", "unrelated_profile",
        "provider_replica", "account_replica", "paper_replica", "scheduler_replica"];
    private readonly JsonElement config, profile, writer;
    private readonly string service, sid;

    internal WriterValidationProtocol(JsonElement configuration)
    {
        config = configuration.Clone();
        profile = config.GetProperty("host").GetProperty("science").GetProperty("custodyPolicy").GetProperty("actor_profile");
        writer = profile.GetProperty("writer");
        service = S(writer, "service_name");
        Need(Regex.IsMatch(service, "^MomentumHunterContinuous-qual-[a-z0-9][a-z0-9-]{0,31}-Writer$"), "SERVICE_NAME");
        var hash = SHA1.HashData(Encoding.Unicode.GetBytes(service.ToUpperInvariant()));
        sid = "S-1-5-80-" + string.Join("-", Enumerable.Range(0, 5).Select(i => BitConverter.ToUInt32(hash, 4 * i)));
        Need(S(profile, "profile") == Profile && S(writer, "integrity_sid") == "S-1-16-12288", "CONFIGURED_PROFILE");
        Need(S(writer.GetProperty("writer_token_contract"), "contract") == "a7-qualified-high-scm-writer-v1", "CONFIGURED_CONTRACT");
    }

    internal string? Validate(byte[] output, byte[] error, int childPid, long childBirth, int parentPid, long parentBirth)
    {
        try
        {
            Need(output.Length is > 0 and <= 65536 && error.Length is > 0 and <= 65536, "STREAM_BOUND");
            using var document = Parse(output);
            var result = document.RootElement;
            Keys(result, "status", "profile", "observation", "serviceDenials", "resourceCount");
            Need(S(result, "status") == "PASS" && S(result, "profile") == Profile, "RESULT_NOT_PASS");
            Need(N(result, "resourceCount") >= 0, "RESOURCE_COUNT");
            var observation = result.GetProperty("observation");
            Need(S(observation, "profile") == Profile && S(observation, "role") == "writer" &&
                S(observation, "provenance") == "ACTUAL_NATIVE_PROCESS_TOKEN_AND_SCM_QUERY" &&
                observation.GetProperty("generation").ValueKind == JsonValueKind.Null, "OBSERVATION");
            var process = observation.GetProperty("process");
            var parent = observation.GetProperty("parent");
            Need(N(process, "pid") == childPid && N(process, "birth") == childBirth &&
                N(parent, "pid") == parentPid && N(parent, "birth") == parentBirth, "ACTOR_IDENTITY");
            Need(S(process, "image") == S(writer, "python_path") && S(parent, "image") == S(writer, "host_path"), "IMAGE_IDENTITY");
            var scm = observation.GetProperty("scm");
            Need(S(scm, "service_name") == service && S(scm, "service_sid") == sid &&
                N(scm, "sid_type") == 3 && N(scm, "pid") == parentPid && N(scm, "state") == 4, "SCM_IDENTITY");
            var privileges = scm.GetProperty("required_privileges").EnumerateArray().Select(x => x.GetString()).ToArray();
            Need(privileges.SequenceEqual(new[] { "SeChangeNotifyPrivilege" }), "SCM_PRIVILEGES");
            var token = observation.GetProperty("token");
            ValidateToken(token);
            ValidateServiceDenials(result.GetProperty("serviceDenials"));
            ValidateDiagnostics(error, observation, token, childPid);
            return null;
        }
        catch (Exception ex) when (ex is JsonException or InvalidDataException or InvalidOperationException or
            KeyNotFoundException or FormatException or OverflowException or ArgumentException or IOException)
        {
            return ex is InvalidDataException ? ex.Message : "WRITER_PROTOCOL_MALFORMED_" + ex.GetType().Name;
        }
    }

    private void ValidateToken(JsonElement token)
    {
        Need(S(token, "user") == "S-1-5-19" && S(token, "owner") == "S-1-5-19" &&
            S(token, "integrity") == "S-1-16-12288" && !B(token, "thread_token"), "TOKEN_PRINCIPAL");
        foreach (var (name, value) in new[] { ("token_type", 1), ("elevation", 0), ("elevation_type", 1),
            ("ui_access", 0), ("virtualization", 0), ("session_id", 0), ("has_restrictions", 1), ("mandatory_policy", 3) })
            Need(N(token, name) == value, "TOKEN_" + name);
        var groups = Attributes(token.GetProperty("group_attributes"));
        var logons = groups.Where(x => (x.Value & 0xC0000000) != 0).ToArray();
        Need(logons.Length == 1 && Regex.IsMatch(logons[0].Key, "^S-1-5-5-[0-9]+-[0-9]+$") &&
            logons[0].Value == 0xC000000F, "TOKEN_LOGON");
        var expected = writer.GetProperty("writer_token_contract").GetProperty("stable_group_sids")
            .EnumerateArray().ToDictionary(x => x.GetString()!, _ => 7L, StringComparer.Ordinal);
        expected.Add(sid, 14); expected.Add("S-1-16-12288", 96); expected.Add(logons[0].Key, 0xC000000F);
        Need(groups.Count == expected.Count && groups.All(x => expected.GetValueOrDefault(x.Key, -1) == x.Value), "TOKEN_GROUPS");
        var restricted = Attributes(token.GetProperty("restricting_attributes"));
        Need(restricted.Count == 4 && new[] { sid, "S-1-1-0", "S-1-5-33", logons[0].Key }
            .All(x => restricted.GetValueOrDefault(x, -1) == 7), "TOKEN_RESTRICTING");
        var privilege = Attributes(token.GetProperty("privilege_attributes"));
        Need(privilege.Count == 1 && privilege.GetValueOrDefault("SeChangeNotifyPrivilege", -1) == 3, "TOKEN_PRIVILEGES");
        foreach (var field in new[] { "token_id", "authentication_id", "modified_id" })
        {
            var pair = token.GetProperty(field);
            Need(pair.GetArrayLength() == 2 && pair.EnumerateArray().All(x => x.TryGetUInt32(out _)), "TOKEN_STATISTICS");
        }
    }

    private void ValidateServiceDenials(JsonElement rows)
    {
        var prefix = service[..^7];
        var expected = (from role in new[] { "Automation", "Runtime", "Writer", "Science" }
                        from right in ServiceRights select (prefix + "-" + role, (long)right)).ToHashSet();
        Need(rows.GetArrayLength() == expected.Count, "SERVICE_DENIAL_COUNT");
        foreach (var row in rows.EnumerateArray())
        {
            Keys(row, "service", "right", "denied", "win32");
            Need(B(row, "denied") && N(row, "win32") == 5 &&
                expected.Remove((S(row, "service"), N(row, "right"))), "SERVICE_DENIAL");
        }
        Need(expected.Count == 0, "SERVICE_DENIAL_INCOMPLETE");
    }

    private void ValidateDiagnostics(byte[] error, JsonElement observation, JsonElement token, int pid)
    {
        var text = Utf8.GetString(error);
        Need(text.EndsWith('\n'), "TRUNCATED_DIAGNOSTIC");
        var lines = text.Split('\n');
        Need(lines.Length is 4 or 5 && lines[^1].Length == 0, "DIAGNOSTIC_LINE_COUNT");
        var stages = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
        for (int i = 0; i < lines.Length - 2; i++)
        {
            var line = lines[i].TrimEnd('\r');
            Need(line.StartsWith(StageMarker, StringComparison.Ordinal), "UNKNOWN_DIAGNOSTIC");
            using var stage = Parse(Utf8.GetBytes(line[StageMarker.Length..]));
            var value = stage.RootElement;
            Need(S(value, "stage") == "A" + (i + 4), "STAGE_ORDER");
            Need(S(value, "status") is "PASS" or "BLOCKED" && B(value, "tokenUnchanged"), "DIAGNOSTIC_FAILURE");
            stages.Add(S(value, "stage"), value.Clone());
        }
        var terminal = lines[^2].TrimEnd('\r');
        Need(terminal.StartsWith(ReportMarker, StringComparison.Ordinal), "DIAGNOSTIC_REPORT_MISSING");
        var transportText = terminal[ReportMarker.Length..];
        Need(Utf8.GetByteCount(transportText) <= 24000, "DIAGNOSTIC_TRANSPORT_BOUND");
        using var transport = Parse(Utf8.GetBytes(transportText));
        var packet = transport.RootElement;
        Keys(packet, "encoding", "payload", "rawBytes", "sha256");
        Need(S(packet, "encoding") == "zlib-base64-json", "DIAGNOSTIC_ENCODING");
        var length = N(packet, "rawBytes");
        Need(length is > 0 and <= 262144, "DIAGNOSTIC_DECODE_BOUND");
        using var compressed = new MemoryStream(Convert.FromBase64String(S(packet, "payload")));
        using var decoder = new ZLibStream(compressed, CompressionMode.Decompress);
        var raw = new byte[(int)length];
        decoder.ReadExactly(raw);
        Need(decoder.ReadByte() == -1, "DIAGNOSTIC_DECODE_OVERFLOW");
        var digest = S(packet, "sha256");
        Need(digest.Length == 64 && Convert.FromHexString(digest).SequenceEqual(SHA256.HashData(raw)), "DIAGNOSTIC_HASH");
        using var decoded = Parse(raw);
        var report = decoded.RootElement;
        Need(N(report, "schema") == 2 && S(report, "task") == "ARGUS-013B-FIRST-FALSE-ASSUMPTION-LADDER-016J" &&
            S(report, "phase") == "PRE_GENERATION_ADMISSION" && S(report, "serviceRole") == "writer", "DIAGNOSTIC_SCHEMA");
        Need(N(report, "pid") == pid && S(report, "service") == service && S(report, "serviceSid") == sid &&
            S(report, "qualificationInstance") == S(config.GetProperty("host"), "instanceRoot"), "DIAGNOSTIC_ACTOR");
        Need(DigestMatches(S(report, "configurationSha256"), Canonical(config)) &&
            DigestMatches(S(report, "profileSha256"), Canonical(profile)), "DIAGNOSTIC_CONFIG_BINDING");
        Need(S(report, "firstFalseAssumption") == "NONE_REACHED" && B(report, "tokenUnchanged") &&
            B(report, "admissionIdentical") && report.GetProperty("errors").GetArrayLength() == 0, "DIAGNOSTIC_FAILURE");
        Need(!report.TryGetProperty("progressOutputUnavailable", out var missing) || missing.ValueKind == JsonValueKind.False, "DIAGNOSTIC_PROGRESS_MISSING");
        foreach (var field in new[] { "admissionBefore", "admissionAfter", "admissionAfterObservation" })
        {
            if (field == "admissionAfterObservation" && !report.TryGetProperty(field, out _)) continue;
            var admission = report.GetProperty(field);
            Need(S(admission, "result") == "ACCEPT" && admission.GetProperty("predicate").ValueKind == JsonValueKind.Null, "DIAGNOSTIC_ADMISSION_REJECTED");
        }
        var binding = report.GetProperty("binding");
        Need(B(binding, "matched") && Equal(binding.GetProperty("process"), observation.GetProperty("process")) &&
            Equal(binding.GetProperty("parent"), observation.GetProperty("parent")) &&
            Equal(binding.GetProperty("scm"), observation.GetProperty("scm")), "DIAGNOSTIC_BINDING");
        var diagnosticToken = report.GetProperty("token");
        foreach (var field in new[] { "thread_token", "user", "owner", "integrity", "token_type", "elevation", "elevation_type",
            "ui_access", "virtualization", "session_id", "has_restrictions", "group_attributes", "restricting_attributes",
            "privilege_attributes", "token_id", "authentication_id", "modified_id", "mandatory_policy" })
            Need(Equal(token.GetProperty(field), diagnosticToken.GetProperty(field)), "DIAGNOSTIC_TOKEN_CONFLICT");
        var assumptions = report.GetProperty("assumptions");
        Need(assumptions.EnumerateObject().Count() == stages.Count, "STAGE_COUNT");
        foreach (var (name, stage) in stages)
        {
            var stored = assumptions.GetProperty(name);
            Need(stored.EnumerateObject().Count() + 1 == stage.EnumerateObject().Count(), "STAGE_SHAPE");
            foreach (var property in stored.EnumerateObject())
                Need(stage.TryGetProperty(property.Name, out var value) && Equal(value, property.Value), "STAGE_REPORT_CONFLICT");
        }
        var a4 = assumptions.GetProperty("A4");
        Need(S(a4, "status") == "PASS" && B(a4, "actualWriterProcess") && B(a4, "actualWriterTokenEnvelopeComplete"), "A4_DIAGNOSTIC");
        var a5 = assumptions.GetProperty("A5");
        Need(N(a5, "requiredDenials") == 0, "DIAGNOSTIC_REQUIRED_DENIAL");
        var unknown = ValidateFiles(report.GetProperty("files"));
        Need(N(a5, "unknown") == unknown && N(a5, "targets") == report.GetProperty("files").EnumerateArray()
            .Count(x => S(x, "assumption") == "A5"), "DIAGNOSTIC_FILE_COUNTS");
        if (S(a5, "status") == "BLOCKED")
            Need(unknown > 0 && stages.Count == 2 && !B(report, "completed"), "UNEXPLAINED_A5_BLOCK");
        else
        {
            Need(unknown == 0 && stages.Count == 3, "MISSING_A6_DIAGNOSTIC");
            var a6 = assumptions.GetProperty("A6");
            Need(S(a6, "status") == "BLOCKED" && N(a6, "forbiddenGrants") == 0 && N(a6, "unknown") == 0 &&
                !B(a6, "completeAuthorityDomainProven") && S(a6, "limitation") == "FIXED_ROOTS_AND_REPLICA_LEAVES_NOT_GLOBAL_AUTHORITY_PROOF" &&
                B(report, "completed"), "UNEXPLAINED_A6_BLOCK");
            var services = report.GetProperty("services").GetProperty("rows");
            Need(services.GetArrayLength() == 7 * ServiceRights.Length, "DIAGNOSTIC_SERVICE_COUNT");
            foreach (var row in services.EnumerateArray())
                Need(S(row, "classification") == "SECURITY_DENIED" && !B(row, "accessGranted") &&
                    !B(row, "apiSuccess") && N(row, "win32") == 5, "DIAGNOSTIC_SERVICE_GRANT");
        }
    }

    private long ValidateFiles(JsonElement files)
    {
        Need(files.GetArrayLength() is > 0 and <= 128, "DIAGNOSTIC_FILE_BOUND");
        long unknown = 0;
        var seen = new HashSet<(string, string)>();
        foreach (var file in files.EnumerateArray())
        {
            var phase = S(file, "assumption");
            Need(phase is "A5" or "A6" && seen.Add((phase, S(file, "path"))), "DIAGNOSTIC_FILE_IDENTITY");
            var rows = file.GetProperty("rows");
            Need(rows.GetArrayLength() is > 1 and <= 16 && N(rows[0], "right") == 0, "DIAGNOSTIC_RIGHTS");
            if (!B(file, "identityBound"))
            {
                var resource = S(file, "name").Split(':');
                Need(phase == "A5" && resource.Length == 2 && ReplicaNames.Contains(resource[0]) &&
                    resource[1] == "qualification-only.json", "DIAGNOSTIC_UNKNOWN_RESOURCE");
                var matches = profile.GetProperty("resources").EnumerateArray().Where(x => S(x, "name") == resource[0]).ToArray();
                Need(matches.Length == 1 && S(file, "path") == Path.Combine(S(matches[0], "path"), resource[1]), "DIAGNOSTIC_REPLICA_PATH");
                foreach (var row in rows.EnumerateArray())
                    Need(S(row, "classification") is "OBJECT_MISSING" or "PATH_MISSING" && !B(row, "accessGranted") &&
                        !B(row, "apiSuccess") && N(row, "win32") is 2 or 3, "DIAGNOSTIC_REPLICA_FAILURE");
                unknown++;
                continue;
            }
            foreach (var row in rows.EnumerateArray().Skip(1))
            {
                bool granted = phase == "A5";
                Need(S(row, "classification") == (granted ? "GRANTED" : "SECURITY_DENIED") &&
                    B(row, "accessGranted") == granted && B(row, "apiSuccess") == granted &&
                    N(row, "win32") == (granted ? 0 : 5), "DIAGNOSTIC_ACCESS_FAILURE");
            }
        }
        return unknown;
    }

    private static Dictionary<string, long> Attributes(JsonElement value)
    {
        Need(value.GetArrayLength() is > 0 and <= 128, "TOKEN_ATTRIBUTES_BOUND");
        var map = new Dictionary<string, long>(StringComparer.Ordinal);
        foreach (var pair in value.EnumerateArray())
        {
            Need(pair.GetArrayLength() == 2 && pair[1].TryGetUInt32(out _), "TOKEN_ATTRIBUTES_SHAPE");
            Need(map.TryAdd(pair[0].GetString()!, pair[1].GetInt64()), "DUPLICATE_TOKEN_ATTRIBUTE");
        }
        return map;
    }

    private static JsonDocument Parse(byte[] bytes)
    {
        var document = JsonDocument.Parse(Utf8.GetString(bytes), new JsonDocumentOptions { MaxDepth = 64 });
        try { Unique(document.RootElement); return document; }
        catch { document.Dispose(); throw; }
    }

    private static void Unique(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var property in value.EnumerateObject())
            { Need(names.Add(property.Name), "DUPLICATE_JSON_PROPERTY"); Unique(property.Value); }
        }
        else if (value.ValueKind == JsonValueKind.Array)
            foreach (var item in value.EnumerateArray()) Unique(item);
    }

    private static bool Equal(JsonElement a, JsonElement b)
    {
        if (a.ValueKind != b.ValueKind) return false;
        if (a.ValueKind == JsonValueKind.Object)
            return a.EnumerateObject().Count() == b.EnumerateObject().Count() && a.EnumerateObject()
                .All(p => b.TryGetProperty(p.Name, out var v) && Equal(p.Value, v));
        if (a.ValueKind == JsonValueKind.Array)
            return a.GetArrayLength() == b.GetArrayLength() && a.EnumerateArray().Zip(b.EnumerateArray()).All(p => Equal(p.First, p.Second));
        return a.ValueKind == JsonValueKind.String ? a.GetString() == b.GetString() : a.GetRawText() == b.GetRawText();
    }

    internal static byte[] Canonical(JsonElement value)
    {
        string Render(JsonElement item) => item.ValueKind switch
        {
            JsonValueKind.Object => "{" + string.Join(",", item.EnumerateObject().OrderBy(p => p.Name, StringComparer.Ordinal)
                .Select(p => Quote(p.Name) + ":" + Render(p.Value))) + "}",
            JsonValueKind.Array => "[" + string.Join(",", item.EnumerateArray().Select(Render)) + "]",
            JsonValueKind.String => Quote(item.GetString()!),
            _ => item.GetRawText()
        };
        return Utf8.GetBytes(Render(value));
    }

    private static string Quote(string value)
    {
        var encoded = JsonSerializer.Serialize(value, new JsonSerializerOptions
            { Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping });
        var ascii = string.Concat(encoded.Select(c => c >= 127 ? "\\u" + ((int)c).ToString("x4") : c.ToString()));
        return Regex.Replace(ascii, @"\\u[0-9A-Fa-f]{4}", match => match.Value.ToLowerInvariant());
    }

    private static bool DigestMatches(string digest, byte[] bytes) =>
        digest.Length == 64 && Convert.FromHexString(digest).SequenceEqual(SHA256.HashData(bytes));

    private static void Keys(JsonElement value, params string[] keys) =>
        Need(value.ValueKind == JsonValueKind.Object && value.EnumerateObject().Select(p => p.Name).ToHashSet().SetEquals(keys), "RESULT_SCHEMA");
    private static string S(JsonElement value, string name) => value.GetProperty(name).GetString() ?? throw new InvalidDataException("NULL_STRING");
    private static long N(JsonElement value, string name) => value.GetProperty(name).GetInt64();
    private static bool B(JsonElement value, string name) => value.GetProperty(name).GetBoolean();
    private static void Need(bool condition, string code) { if (!condition) throw new InvalidDataException("WRITER_PROTOCOL_" + code); }
}
