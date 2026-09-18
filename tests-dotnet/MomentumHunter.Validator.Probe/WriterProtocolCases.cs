using System.Diagnostics;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using MomentumHunter.ContinuousServiceHost;

internal static class WriterProtocolCases
{
    private const string Marker = "WRITER_SELF_AUTHORITY_016J=";
    private const string Stage = "WRITER_ASSUMPTION_016J=";
    private static void Need(bool value, string message) { if (!value) throw new Exception(message); }
    private static JsonElement Element(JsonNode value) => JsonSerializer.SerializeToElement(value);
    private static byte[] Bytes(JsonNode value) => Encoding.UTF8.GetBytes(value.ToJsonString());
    private static string Hash(JsonNode value) => Convert.ToHexString(SHA256.HashData(WriterValidationProtocol.Canonical(Element(value))));

    private static JsonNode Decode(byte[] bytes)
    {
        var line = Encoding.UTF8.GetString(bytes).Split('\n').Single(x => x.StartsWith(Marker));
        var packet = JsonNode.Parse(line[Marker.Length..])!;
        using var zipped = new MemoryStream(Convert.FromBase64String(packet["payload"]!.GetValue<string>()));
        using var decoder = new ZLibStream(zipped, CompressionMode.Decompress);
        using var output = new MemoryStream(); decoder.CopyTo(output);
        return JsonNode.Parse(output.ToArray())!;
    }

    private static byte[] Encode(JsonNode report)
    {
        var raw = WriterValidationProtocol.Canonical(Element(report));
        using var zipped = new MemoryStream();
        using (var encoder = new ZLibStream(zipped, CompressionLevel.SmallestSize, true)) encoder.Write(raw);
        var packet = new { encoding = "zlib-base64-json", payload = Convert.ToBase64String(zipped.ToArray()),
            rawBytes = raw.Length, sha256 = Convert.ToHexString(SHA256.HashData(raw)) };
        var lines = report["assumptions"]!.AsObject().Select(pair =>
        {
            var stage = pair.Value!.DeepClone(); stage["stage"] = pair.Key;
            return Stage + stage.ToJsonString();
        }).Append(Marker + JsonSerializer.Serialize(packet));
        return Encoding.UTF8.GetBytes(string.Join("\n", lines) + "\n");
    }

    internal static async Task<int> Run(string[] args)
    {
        if (args[0] == "writer-child") return await Child(args);
        var root = Path.GetFullPath(args[1]);
        Directory.CreateDirectory(root);
        var fixture = Path.GetFullPath(args[2]);
        var originalOut = File.ReadAllBytes(Path.Combine(fixture, "002-stdout.bin"));
        var originalErr = File.ReadAllBytes(Path.Combine(fixture, "003-stderr.bin"));
        var configuration = JsonNode.Parse(File.ReadAllBytes(Path.Combine(fixture, "004-continuous-deployment.json")))!;
        var original = JsonNode.Parse(originalOut)!;
        var observed = original["observation"]!;
        var report = Decode(originalErr);
        var policy = new WriterValidationProtocol(Element(configuration));
        string? Check(byte[] stdout, byte[] stderr) => policy.Validate(stdout, stderr,
            observed["process"]!["pid"]!.GetValue<int>(), observed["process"]!["birth"]!.GetValue<long>(),
            observed["parent"]!["pid"]!.GetValue<int>(), observed["parent"]!["birth"]!.GetValue<long>());
        var results = new List<object>();
        void Case(string name, byte[] stdout, byte[] stderr, bool accept)
        {
            var failure = Check(stdout, stderr);
            Need((failure is null) == accept, name + ": " + failure);
            results.Add(new { name, expectedAccepted = accept, actualAccepted = failure is null, failure });
        }
        Case("EXACT_019A_8432_6316", originalOut, originalErr, true);
        Case("EMPTY", [], originalErr, false);
        Case("MALFORMED", Encoding.UTF8.GetBytes("{"), originalErr, false);
        Case("TRUNCATED", originalOut[..^3], originalErr, false);
        Case("DUPLICATE_KEY", Encoding.UTF8.GetBytes("{\"status\":\"PASS\"," + Encoding.UTF8.GetString(originalOut).TrimStart()[1..]), originalErr, false);
        Case("INVALID_UTF8", [0xff, 0xfe], originalErr, false);
        Case("NO_DIAGNOSTIC", originalOut, [], false);
        Case("UNKNOWN_STDERR", originalOut, Encoding.UTF8.GetBytes("unexpected\n"), false);
        Case("NO_REPORT", originalOut, Encoding.UTF8.GetBytes(Encoding.UTF8.GetString(originalErr).Split(Marker)[0]), false);
        Case("TRUNCATED_REPORT", originalOut, originalErr[..^20], false);
        foreach (var (name, mutate) in new (string, Action<JsonNode>)[]
        {
            ("STRUCTURED_FAIL", x => x["status"] = "FAIL"),
            ("WRONG_PROFILE", x => x["profile"] = "OTHER"),
            ("TOKEN_USER", x => x["observation"]!["token"]!["user"] = "S-1-5-18"),
            ("TOKEN_INTEGRITY", x => x["observation"]!["token"]!["integrity"] = "S-1-16-16384"),
            ("TOKEN_ELEVATED", x => x["observation"]!["token"]!["elevation"] = 1),
            ("TOKEN_RESTRICTED", x => x["observation"]!["token"]!["has_restrictions"] = 0),
            ("TOKEN_GROUP", x => x["observation"]!["token"]!["group_attributes"]![0]![1] = 7),
            ("TOKEN_PRIVILEGE", x => x["observation"]!["token"]!["privilege_attributes"]![0]![0] = "SeDebugPrivilege"),
            ("TOKEN_LOGON", x => x["observation"]!["token"]!["group_attributes"]![8]![1] = 7),
            ("TOKEN_MANDATORY_POLICY", x => x["observation"]!["token"]!["mandatory_policy"] = 1),
            ("PARENT_MISMATCH", x => x["observation"]!["parent"]!["pid"] = 1),
            ("CHILD_BIRTH", x => x["observation"]!["process"]!["birth"] = 1),
            ("IMAGE_MISMATCH", x => x["observation"]!["process"]!["image"] = "wrong.exe"),
            ("SERVICE_GRANT", x => x["serviceDenials"]![0]!["denied"] = false),
            ("SERVICE_MISSING", x => x["serviceDenials"]!.AsArray().RemoveAt(0)),
            ("SERVICE_DUPLICATE", x => x["serviceDenials"]![1] = x["serviceDenials"]![0]!.DeepClone()),
            ("NEGATIVE_RESOURCES", x => x["resourceCount"] = -1),
            ("MISSING_OBSERVATION", x => x.AsObject().Remove("observation"))
        }) { var value = original.DeepClone(); mutate(value); Case(name, Bytes(value), originalErr, false); }
        foreach (var (name, mutate) in new (string, Action<JsonNode>)[]
        {
            ("DIAGNOSTIC_FALSE", x => x["assumptions"]!["A5"]!["status"] = "FALSE"),
            ("DIAGNOSTIC_ERROR", x => x["errors"]!.AsArray().Add(new JsonObject { ["type"] = "ValueError" })),
            ("DIAGNOSTIC_REJECT", x => x["admissionAfter"]!["result"] = "REJECT"),
            ("DIAGNOSTIC_DENIAL", x => x["assumptions"]!["A5"]!["requiredDenials"] = 1),
            ("DIAGNOSTIC_TOKEN_CHANGED", x => x["tokenUnchanged"] = false),
            ("DIAGNOSTIC_TOKEN_CONFLICT", x => x["token"]!["integrity"] = "S-1-16-16384"),
            ("DIAGNOSTIC_CONFIG_CONFLICT", x => x["configurationSha256"] = new string('0', 64)),
            ("DIAGNOSTIC_PROFILE_CONFLICT", x => x["profileSha256"] = new string('0', 64)),
            ("DIAGNOSTIC_UNKNOWN_COUNT", x => x["assumptions"]!["A5"]!["unknown"] = 0),
            ("DIAGNOSTIC_FIRST_FALSE", x => x["firstFalseAssumption"] = "A5"),
            ("DIAGNOSTIC_PATH_ESCAPE", x => x["files"]!.AsArray().First(n => n!["identityBound"]!.GetValue<bool>() == false)!["path"] = "C:\\escape"),
            ("DIAGNOSTIC_MISSING_REAL_RESOURCE", x => x["files"]!.AsArray().First(n => n!["identityBound"]!.GetValue<bool>() == false)!["name"] = "runtime_source:qualification-only.json"),
            ("DIAGNOSTIC_OVERSIZE", x => x["testPadding"] = new string('x', 300000))
        }) { var value = report.DeepClone(); mutate(value); Case(name, originalOut, Encode(value), false); }
        var stageConflict = Encoding.UTF8.GetString(originalErr).Replace("\"actualWriterProcess\":true", "\"actualWriterProcess\":false", StringComparison.Ordinal);
        Case("PROGRESS_REPORT_DISAGREEMENT", originalOut, Encoding.UTF8.GetBytes(stageConflict), false);
        var corrupt = Encoding.UTF8.GetString(originalErr).Replace("\"sha256\":\"", "\"sha256\":\"0", StringComparison.Ordinal);
        Case("BAD_DIGEST_LENGTH", originalOut, Encoding.UTF8.GetBytes(corrupt), false);
        var large = report.DeepClone(); large["testPadding"] = new string('x', 100000);
        Case("BOUNDED_LARGE_DIAGNOSTIC", originalOut, Encode(large), true);
        var missing = report.DeepClone(); missing["errors"] = null;
        Case("NULL_ERRORS", originalOut, Encode(missing), false);
        foreach (var (name, value) in new[]
        {
            ("NONZERO_EXIT", new ValidatorResult(7, null, 8432, 6316, true, null)),
            ("CANCELLED", new ValidatorResult(0, "CALLER", 8432, 6316, true, null)),
            ("TIMEOUT", new ValidatorResult(0, "TIMER", 8432, 6316, true, null)),
            ("OVERFLOW", new ValidatorResult(0, null, 65537, 6316, true, null)),
            ("STDERR_OVERFLOW", new ValidatorResult(0, null, 8432, 65537, true, null)),
            ("INCOMPLETE_CLEANUP", new ValidatorResult(0, null, 8432, 6316, false, null)),
            ("UNEXPECTED_EXCEPTION", new ValidatorResult(0, null, 8432, 6316, true, "failure"))
        })
        { Need(!(value with { ProtocolAccepted = true }).Accepted, name); results.Add(new { name, rejected = true }); }

        // Synthetic child fixtures exercise IPC/runner policy, never claim a real SCM token.
        var syntheticConfig = configuration.DeepClone();
        var actor = syntheticConfig["host"]!["science"]!["custodyPolicy"]!["actor_profile"]!["writer"]!;
        actor["host_path"] = Environment.ProcessPath!; actor["python_path"] = Environment.ProcessPath!;
        var configPath = Path.Combine(root, "synthetic-config.json");
        File.WriteAllBytes(configPath, Bytes(syntheticConfig));
        var syntheticPolicy = new WriterValidationProtocol(Element(syntheticConfig));
        foreach (var mode in new[] { "success", "large", "fail", "exit", "crash", "stderr", "empty", "malformed", "flood", "stderr-flood", "wait", "caller", "precanceled" })
        {
            var info = new ProcessStartInfo(Environment.ProcessPath!);
            if (Path.GetFileNameWithoutExtension(info.FileName).Equals("dotnet", StringComparison.OrdinalIgnoreCase)) info.ArgumentList.Add(typeof(WriterProtocolCases).Assembly.Location);
            foreach (var arg in new[] { "writer-child", mode, fixture, configPath, Environment.ProcessId.ToString() }) info.ArgumentList.Add(arg);
            using var cancel = new CancellationTokenSource();
            if (mode == "precanceled") cancel.Cancel();
            var directory = Path.Combine(root, "process-" + mode);
            var task = QualificationValidator.RunAsync(info, directory, TimeSpan.FromSeconds(mode == "wait" ? 1 : 20), cancel.Token,
                writerProtocol: syntheticPolicy);
            if (mode == "caller")
            {
                var timer = Stopwatch.StartNew();
                while (!File.Exists(Path.Combine(directory, "stdout.bin")) || new FileInfo(Path.Combine(directory, "stdout.bin")).Length == 0)
                { Need(!task.IsCompleted && timer.Elapsed.TotalSeconds < 15, "Child readiness"); await Task.Delay(10); }
                cancel.Cancel();
            }
            var result = await task;
            Need(result.Accepted == (mode is "success" or "large"), mode + ": " + JsonSerializer.Serialize(result));
            Need(File.Exists(Path.Combine(directory, "result.json")), "Durable terminal missing");
            if (mode == "wait") Need(result.CancellationSource == "TIMER", "Timeout classification");
            if (mode == "caller") Need(result.CancellationSource == "CALLER", "Caller classification");
            results.Add(new { name = "PROCESS_" + mode, result });
        }
        var summary = new { status = "PASS", cases = results.Count, results, historicalInputHashes = new {
            stdout = Convert.ToHexString(SHA256.HashData(originalOut)), stderr = Convert.ToHexString(SHA256.HashData(originalErr)) },
            actualScmRetest = false, processFixtures = "SYNTHETIC_PROTOCOL_ONLY", providerContact = false };
        File.WriteAllText(Path.Combine(root, "WRITER-PROTOCOL-TESTS.json"), JsonSerializer.Serialize(summary, new JsonSerializerOptions { WriteIndented = true }));
        Console.WriteLine(JsonSerializer.Serialize(new { summary.status, summary.cases }));
        return 0;
    }

    private static async Task<int> Child(string[] args)
    {
        var mode = args[1]; var fixture = args[2];
        if (mode == "crash") throw new InvalidOperationException("CONTROLLED_TEST_CRASH");
        if (mode is "wait" or "caller") { Console.Write("ready"); Console.Out.Flush(); await Task.Delay(60000); return 0; }
        if (mode is "flood" or "stderr-flood")
        { (mode == "flood" ? Console.Out : Console.Error).Write(new string('x', 100000)); await Task.Delay(60000); return 0; }
        if (mode == "empty") return 0;
        if (mode == "malformed") { Console.Write("{"); return 0; }
        var configuration = JsonNode.Parse(File.ReadAllBytes(args[3]))!;
        var result = JsonNode.Parse(File.ReadAllBytes(Path.Combine(fixture, "002-stdout.bin")))!;
        var report = Decode(File.ReadAllBytes(Path.Combine(fixture, "003-stderr.bin")));
        using var own = Process.GetCurrentProcess();
        using var parent = Process.GetProcessById(int.Parse(args[4]));
        var obs = result["observation"]!;
        obs["process"]!["pid"] = own.Id; obs["process"]!["birth"] = own.StartTime.ToUniversalTime().ToFileTimeUtc();
        obs["process"]!["image"] = Environment.ProcessPath!;
        obs["parent"]!["pid"] = parent.Id; obs["parent"]!["birth"] = parent.StartTime.ToUniversalTime().ToFileTimeUtc();
        obs["parent"]!["image"] = Environment.ProcessPath!; obs["scm"]!["pid"] = parent.Id;
        report["pid"] = own.Id;
        foreach (var field in new[] { "process", "parent", "scm" }) report["binding"]![field] = obs[field]!.DeepClone();
        report["configurationSha256"] = Hash(configuration);
        report["profileSha256"] = Hash(configuration["host"]!["science"]!["custodyPolicy"]!["actor_profile"]!);
        if (mode == "large") report["testPadding"] = new string('x', 100000);
        if (mode == "fail") result["status"] = "FAIL";
        var stdout = Bytes(result); var stderr = Encode(report);
        // Concurrent writes expose sequential-drain/backpressure regressions.
        await Task.WhenAll(Console.OpenStandardOutput().WriteAsync(stdout).AsTask(), Console.OpenStandardError().WriteAsync(stderr).AsTask());
        if (mode == "stderr") Console.Error.Write("unexpected\n");
        return mode == "exit" ? 7 : 0;
    }
}
