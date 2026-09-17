using System.Diagnostics;
using System.Text.Json.Nodes;

namespace MomentumHunter.ContinuousServiceHost;

[System.Runtime.Versioning.SupportedOSPlatform("windows")]
internal sealed class DirectScienceGeneration : IDisposable
{
    private readonly string root, status, fingerprint;
    private readonly FileStream lease;
    private readonly JsonObject identity;
    internal string Generation { get; } = Guid.NewGuid().ToString("D");
    internal DirectScienceGeneration(JsonObject config)
    {
        fingerprint = config["hostFingerprint"]!.GetValue<string>();
        root = Path.Combine(config["hostStateRoot"]!.GetValue<string>(), "science");
        status = Path.Combine(config["logRoot"]!.GetValue<string>(), "science", "status.json");
        lease = new FileStream(Path.Combine(root, "supervisor.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        try
        {
            using var current = Process.GetCurrentProcess();
            identity = new JsonObject { ["hostFingerprint"] = fingerprint, ["role"] = "science", ["generation"] = Generation,
                ["executionModel"] = "SCM_DIRECT_SCIENCE_SERVICE_PROCESS", ["servicePid"] = current.Id,
                ["serviceBirth"] = current.StartTime.ToUniversalTime().ToFileTimeUtc(), ["phase"] = "RUNNING" };
            Write("generation.json", identity);
        }
        catch { lease.Dispose(); throw; }
    }
    internal void Returned(int code)
    {
        JsonObject health;
        try { health = JsonNode.Parse(File.ReadAllBytes(status))!.AsObject(); }
        catch (Exception ex) when (ex is IOException or System.Text.Json.JsonException or InvalidOperationException)
        { health = new JsonObject(); }
        var exact = health["hostFingerprint"]?.GetValue<string>() == fingerprint && health["generation"]?.GetValue<string>() == Generation;
        var receipt = exact ? health.DeepClone().AsObject() : new JsonObject();
        foreach (var key in new[] { "hostFingerprint", "role", "generation", "executionModel", "servicePid", "serviceBirth" })
            receipt[key] = identity[key]?.DeepClone();
        receipt["exitCode"] = code;
        if (!exact || code != 0 || health["state"]?.GetValue<string>() != "STOPPED")
        { receipt["drainComplete"] = false; receipt["cleanupComplete"] = false; }
        receipt["observedAt"] = DateTimeOffset.UtcNow.ToString("O");
        Write("completion-" + Generation + ".json", receipt, true);
        Write("completion.json", receipt);
        // The dependent verifier must separately prove this PID/birth exited.
        identity["phase"] = "RETURNED_PENDING_SERVICE_EXIT";
        Write("generation.json", identity);
    }
    private void Write(string name, JsonObject value, bool once = false)
    {
        var target = Path.Combine(root, name);
        var temp = target + "." + Guid.NewGuid().ToString("N") + ".tmp";
        using (var stream = new FileStream(temp, FileMode.CreateNew, FileAccess.Write, FileShare.None))
        { System.Text.Json.JsonSerializer.Serialize(stream, value); stream.Flush(true); }
        File.Move(temp, target, !once);
    }
    public void Dispose() => lease.Dispose();
}
