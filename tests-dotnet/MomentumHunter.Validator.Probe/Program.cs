using System.Diagnostics;
using System.Text.Json;
using MomentumHunter.ContinuousServiceHost;

if (args.Length > 0 && args[0] is "writer-suite" or "writer-child") return await WriterProtocolCases.Run(args);
if (args.Length == 3 && args[0] == "custody-file-matrix")
{
    using var config = JsonDocument.Parse(File.ReadAllBytes(args[1]));
    using var cases = JsonDocument.Parse(File.ReadAllBytes(args[2]));
    var protocol = new WriterValidationProtocol(config.RootElement);
    var flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
    var targets = typeof(WriterValidationProtocol).GetMethod("DiagnosticTargets", flags)!.Invoke(protocol, null)!;
    var validate = typeof(WriterValidationProtocol).GetMethod("ValidateFiles", flags)!;
    foreach (var item in cases.RootElement.EnumerateArray())
    {
        bool accepted;
        try { validate.Invoke(protocol, [item.GetProperty("files"), targets, item.GetProperty("requiredOnly").GetBoolean()]); accepted = true; }
        catch (System.Reflection.TargetInvocationException ex) when (ex.InnerException is InvalidDataException) { accepted = false; }
        if (accepted != item.GetProperty("accepted").GetBoolean()) throw new Exception("MATRIX_RESULT:" + item.GetProperty("name").GetString());
    }
    Console.WriteLine("020G_COMPILED_FILE_MATRIX=PASS; CASES=" + cases.RootElement.GetArrayLength());
    return 0;
}
if (args.Length == 3 && args[0] == "custody-targets")
{
    using var config = JsonDocument.Parse(File.ReadAllBytes(args[1]));
    using var expected = JsonDocument.Parse(File.ReadAllBytes(args[2]));
    var protocol = new WriterValidationProtocol(config.RootElement);
    var method = typeof(WriterValidationProtocol).GetMethod("DiagnosticTargets", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
    var targets = (System.Collections.IEnumerable)method.Invoke(protocol, null)!;
    var serialized = new List<System.Text.Json.Nodes.JsonObject>();
    foreach (var target in targets)
    {
        var node = JsonSerializer.SerializeToNode(target)!.AsObject();
        node["Required"] = JsonSerializer.SerializeToNode(target!.GetType().GetProperty("Required",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(target));
        serialized.Add(node);
    }
    var actual = JsonSerializer.SerializeToElement(serialized);
    var reference = expected.RootElement.EnumerateArray().ToDictionary(x => x.GetProperty("path").GetString()!, StringComparer.Ordinal);
    foreach (var row in actual.EnumerateArray())
    {
        if (!reference.Remove(row.GetProperty("Path").GetString()!, out var other)) throw new Exception("TARGET_PATH_DIFF");
        foreach (var (left, right) in new[] { ("Name", "name"), ("Directory", "directory"), ("Needed", "needed"),
            ("Forbidden", "forbidden"), ("FrozenIdentity", "frozenIdentity"), ("Policy", "policy"), ("Required", "required") })
            if (!WriterValidationProtocol.Canonical(row.GetProperty(left)).SequenceEqual(WriterValidationProtocol.Canonical(other.GetProperty(right))))
                throw new Exception("TARGET_POLICY_DIFF:" + left + ":" + row.GetProperty("Path").GetString());
    }
    if (reference.Count != 0) throw new Exception("TARGETS_OMITTED");
    Console.WriteLine("020G_PYTHON_COMPILED_TARGET_PARITY=PASS; COUNT=" + actual.GetArrayLength());
    return 0;
}

if (args.Length > 0 && args[0] == "child")
{
    switch (args[1])
    {
        case "success": Console.Write("{\"plan\":true}"); return 0;
        case "nonzero": Console.Error.Write("diagnostic"); return 7;
        case "stderr": Console.Write("plan"); Console.Error.Write("unexpected"); return 0;
        case "flood": Console.Write(new string('x', 100000)); await Task.Delay(60000); return 0;
        case "wait": Console.Write("started"); Console.Out.Flush(); await Task.Delay(60000); return 0;
        default: throw new ArgumentException("Unknown synthetic case.");
    }
}
var root = Path.GetFullPath(args[0]);
Directory.CreateDirectory(root);
ProcessStartInfo Child(string mode)
{
    var info = new ProcessStartInfo(Environment.ProcessPath!);
    if (Path.GetFileNameWithoutExtension(info.FileName).Equals("dotnet", StringComparison.OrdinalIgnoreCase))
        info.ArgumentList.Add(typeof(Program).Assembly.Location);
    info.ArgumentList.Add("child"); info.ArgumentList.Add(mode);
    return info;
}
void Require(bool condition, string code) { if (!condition) throw new Exception(code); }
var results = new List<object>();
foreach (var mode in new[] { "success", "nonzero", "stderr", "flood", "wait", "caller", "precanceled", "missing" })
{
    using var cancel = new CancellationTokenSource();
    if (mode == "precanceled") cancel.Cancel();
    var info = mode == "missing" ? new ProcessStartInfo(Path.Combine(root, "no-such-executable.exe"))
        : Child(mode is "caller" or "precanceled" ? "wait" : mode);
    var path = Path.Combine(root, mode);
    var task = QualificationValidator.RunAsync(info, path,
        TimeSpan.FromSeconds(mode == "wait" ? 1 : 20), cancel.Token);
    if (mode == "caller")
    {
        var deadline = Stopwatch.StartNew();
        while (!File.Exists(Path.Combine(path, "stdout.bin")) || new FileInfo(Path.Combine(path, "stdout.bin")).Length == 0)
        {
            Require(!task.IsCompleted && deadline.Elapsed < TimeSpan.FromSeconds(15), "Child readiness not observed");
            await Task.Delay(10);
        }
        cancel.Cancel();
    }
    var result = await task;
    Require(result.Accepted == (mode == "success"), "Acceptance mismatch: " + mode);
    Require(File.Exists(Path.Combine(path, "result.json")), "Missing durable terminal receipt");
    var events = File.ReadAllLines(Path.Combine(path, "events.jsonl")).Select(x => JsonDocument.Parse(x)).ToArray();
    Require(events.Last().RootElement.GetProperty("stage").GetString() == "TERMINAL", "Terminal ordering");
    if (mode == "nonzero") Require(result.ExitCode == 7 && result.StderrBytes == 10, "Nonzero evidence lost");
    if (mode == "wait") Require(result.CancellationSource == "TIMER", "Timer confused with caller");
    if (mode == "caller") Require(result.CancellationSource == "CALLER", "Caller confused with timer");
    if (mode == "flood") Require(result.CancellationSource == "STDOUT_LIMIT" && new FileInfo(Path.Combine(path, "stdout.bin")).Length == 65536, "Unbounded output");
    if (mode is "precanceled" or "missing") Require(!events.Any(x => x.RootElement.GetProperty("stage").GetString() == "CHILD_STARTED"), "Unexpected child");
    results.Add(new { mode, result });
    foreach (var entry in events) entry.Dispose();
}
Console.WriteLine(JsonSerializer.Serialize(new { status = "PASS", cases = results.Count, results }));
return 0;
