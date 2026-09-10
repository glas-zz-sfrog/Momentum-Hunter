using System.Text.Json;

namespace MomentumHunter.AutomationService;

public enum RetryCommitStage { BeforeReservation, ReservedBeforePublication, PublishedBeforeBorrow, Borrowed }

public sealed record RetryDecisionRecord(int SchemaVersion, string ContractHash, string AttemptId,
    string Decision, DateTimeOffset ReservedAtUtc);

/// <summary>Write-once arbitration before either receipt publication or termination.</summary>
public static class RetryDecision
{
    public const string Commit = "COMMIT_RESERVED";
    public const string Abort = "ABORT_RESERVED";

    public static string? Read(string contractPath, string hash, string attempt)
    {
        var path = contractPath + ".decision.json";
        if (!File.Exists(path)) return null;
        var value = RetryLaunchGate.Decode<RetryDecisionRecord>(File.ReadAllBytes(path));
        if (value.SchemaVersion != 1 || value.ContractHash != hash || value.AttemptId != attempt
            || value.Decision is not (Commit or Abort) || value.ReservedAtUtc > DateTimeOffset.UtcNow)
            throw new InvalidOperationException("RETRY_DECISION_INVALID");
        return value.Decision;
    }

    public static string Reserve(string contractPath, string hash, string attempt, string decision)
    {
        if (decision is not (Commit or Abort)) throw new ArgumentException("RETRY_DECISION_UNKNOWN");
        var existing = Read(contractPath, hash, attempt);
        if (existing is not null) return existing;
        var path = contractPath + ".decision.json";
        var temporary = path + ".partial-" + Guid.NewGuid().ToString("N");
        var raw = JsonSerializer.SerializeToUtf8Bytes(
            new RetryDecisionRecord(1, hash, attempt, decision, DateTimeOffset.UtcNow), RetryLaunchGate.JsonOptions);
        using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None,
            4096, FileOptions.WriteThrough))
        { file.Write(raw); file.Flush(true); }
        // Same-directory no-replace rename is the sole winner selection. A losing
        // temporary file is retained as evidence; it grants no decision authority.
        try { File.Move(temporary, path, false); }
        catch (IOException) when (File.Exists(path)) { }
        return Read(contractPath, hash, attempt) ?? throw new InvalidOperationException("RETRY_DECISION_NOT_PUBLISHED");
    }
}
