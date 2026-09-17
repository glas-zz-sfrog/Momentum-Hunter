using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MomentumHunter.ContinuousServiceHost;

internal sealed class HostProcessGeneration : IDisposable
{
    private readonly string root;
    private readonly string status;
    private readonly string fingerprint;
    private readonly string role;
    private readonly FileStream lease;
    private readonly JsonObject identity;
    public string Generation { get; } = Guid.NewGuid().ToString("D");

    public HostProcessGeneration(string configPath, string role)
    {
        using var document = JsonDocument.Parse(File.ReadAllBytes(configPath));
        var config = document.RootElement;
        this.role = role;
        fingerprint = config.GetProperty("hostFingerprint").GetString()!;
        root = Path.Combine(config.GetProperty("hostStateRoot").GetString()!, role);
        status = Path.Combine(config.GetProperty("logRoot").GetString()!, role, "status.json");
        Directory.CreateDirectory(root);
        lease = new FileStream(Path.Combine(root, "supervisor.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        using var parent = Process.GetCurrentProcess();
        identity = new JsonObject { ["hostFingerprint"] = fingerprint, ["role"] = role,
            ["generation"] = Generation, ["supervisorPid"] = parent.Id,
            ["supervisorBirth"] = parent.StartTime.ToUniversalTime().ToFileTimeUtc(), ["phase"] = "STARTING" };
        Write("generation.json", identity);
    }

    public void Started(Process child)
    {
        identity["childPid"] = child.Id;
        identity["childBirth"] = child.StartTime.ToUniversalTime().ToFileTimeUtc();
        identity["phase"] = "RUNNING";
        Write("generation.json", identity);
    }

    public void StopRequested()
    {
        identity["phase"] = "STOP_REQUESTED";
        Write("generation.json", identity);
    }

    public void Exited(int exitCode)
    {
        var child = new JsonObject();
        try { child = JsonNode.Parse(File.ReadAllBytes(status)) as JsonObject ?? child; }
        catch (Exception exception) when (exception is IOException or JsonException) { }
        var exact = child["hostFingerprint"]?.GetValue<string>() == fingerprint &&
                    child["generation"]?.GetValue<string>() == Generation;
        var receipt = exact ? child.DeepClone().AsObject() : new JsonObject();
        receipt["hostFingerprint"] = fingerprint;
        receipt["role"] = role;
        receipt["generation"] = Generation;
        receipt["exitCode"] = exitCode;
        if (!exact || exitCode != 0 || child["state"]?.GetValue<string>() != "STOPPED")
        {
            receipt["drainComplete"] = false;
            receipt["cleanupComplete"] = false;
        }
        receipt["observedAt"] = DateTimeOffset.UtcNow.ToString("O");
        Write($"completion-{Generation}.json", receipt, once: true);
        Write("completion.json", receipt);
        identity["phase"] = "EXITED";
        Write("generation.json", identity);
    }

    private void Write(string name, JsonObject payload, bool once = false)
    {
        var destination = Path.Combine(root, name);
        var temporary = destination + "." + Guid.NewGuid().ToString("N") + ".tmp";
        using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
        {
            JsonSerializer.Serialize(stream, payload);
            stream.Flush(flushToDisk: true);
        }
        File.Move(temporary, destination, overwrite: !once);
    }

    public void Dispose() => lease.Dispose();
}
