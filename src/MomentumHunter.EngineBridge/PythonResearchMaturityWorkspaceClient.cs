using System.Globalization;
using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.EngineBridge;

public sealed class PythonResearchMaturityWorkspaceClient : IResearchMaturityWorkspaceClient
{
    private readonly IPythonEngineHostConnection _connection;

    public PythonResearchMaturityWorkspaceClient(IPythonEngineHostConnection connection)
    {
        _connection = connection;
    }

    public async Task<ResearchMaturitySnapshot> GetSnapshotAsync(
        CancellationToken cancellationToken = default) =>
        PythonResearchMaturitySnapshotMapper.Map(
            await _connection.GetResearchMaturitySnapshotAsync(cancellationToken));
}

public static class PythonResearchMaturitySnapshotMapper
{
    public static ResearchMaturitySnapshot Map(JsonElement root)
    {
        RequireObject(root, "The Python research-maturity snapshot must be a JSON object.");
        var schemaVersion = RequiredInteger(root, "schemaVersion");
        if (schemaVersion != 1)
        {
            throw new InvalidDataException(
                $"Unsupported Python research-maturity schema version: {schemaVersion}.");
        }

        var state = State(RequiredString(root, "state"));
        var maturityAlerts = new ResearchMaturityAlertCounts(
            NonNegativeInteger(root, "maturityTotalAlerts"),
            NonNegativeInteger(root, "maturityCompletedAlerts"),
            NonNegativeInteger(root, "maturityPendingAlerts"),
            NonNegativeInteger(root, "maturityUnscorableAlerts"),
            OptionalPercentage(root, "maturityCompletionRatePct"));
        var censusAlerts = new ResearchMaturityAlertCounts(
            NonNegativeInteger(root, "censusTotalAlerts"),
            NonNegativeInteger(root, "censusCompletedAlerts"),
            NonNegativeInteger(root, "censusPendingAlerts"),
            NonNegativeInteger(root, "censusUnscorableAlerts"),
            OptionalPercentage(root, "censusCompletionRatePct"));
        var evidenceGate = EvidenceGate(RequiredObject(root, "evidenceGate"));
        var gates = RequiredArray(root, "gates").Select(Gate).ToArray();
        var questions = RequiredArray(root, "questions").Select(Question).ToArray();
        var tableCounts = RequiredArray(root, "tableCounts").Select(TableCount).ToArray();
        var gateCount = NonNegativeInteger(root, "gateCount");
        var displayedGateCount = NonNegativeInteger(root, "displayedGateCount");
        var questionCount = NonNegativeInteger(root, "questionCount");
        var displayedQuestionCount = NonNegativeInteger(root, "displayedQuestionCount");
        var tableCount = NonNegativeInteger(root, "tableCount");
        var displayedTableCount = NonNegativeInteger(root, "displayedTableCount");
        var strategyOptimizationStatus = RequiredString(root, "strategyOptimizationStatus");
        var strategyChangeAllowed = RequiredBoolean(
            root,
            "strategyChangeRecommendationsAllowed");
        var researchOnly = RequiredBoolean(root, "researchOnly");
        var readOnly = RequiredBoolean(root, "readOnly");
        var census = new ResearchEvidenceCensus(
            censusAlerts,
            NonNegativeInteger(root, "captures"),
            NonNegativeInteger(root, "candidateRows"),
            NonNegativeInteger(root, "studyEligibleCaptures"),
            NonNegativeInteger(root, "quarantinedCaptures"),
            NonNegativeInteger(root, "minuteBars"),
            NonNegativeInteger(root, "minuteBarSymbols"),
            NonNegativeInteger(root, "evidenceRuns"),
            NonNegativeInteger(root, "evidenceMetrics"),
            NonNegativeInteger(root, "candidateReviews"),
            NonNegativeInteger(root, "watchlistItems"),
            NonNegativeInteger(root, "entryPlans"),
            NonNegativeInteger(root, "completeEntryPlans"),
            NonNegativeInteger(root, "incompleteEntryPlans"),
            tableCounts,
            tableCount);
        var snapshot = new ResearchMaturitySnapshot(
            schemaVersion,
            state,
            RequiredTimestamp(root, "observedAt"),
            OptionalTimestamp(root, "sourceAsOf"),
            OptionalTimestamp(root, "maturityGeneratedAt"),
            OptionalTimestamp(root, "censusGeneratedAt"),
            RequiredString(root, "sourceLabel"),
            RequiredString(root, "summary"),
            RequiredString(root, "maturityOverallStatus"),
            RequiredString(root, "censusOverallStatus"),
            RequiredString(root, "sampleConfidence"),
            RequiredString(root, "measurableEdgeStatus"),
            strategyOptimizationStatus,
            strategyChangeAllowed,
            maturityAlerts,
            NonNegativeInteger(root, "evidenceNeededToNextGate"),
            evidenceGate,
            gates,
            gateCount,
            questions,
            questionCount,
            census,
            RequiredStringArray(root, "warnings"),
            RequiredStringArray(root, "safetyNotes"),
            researchOnly,
            readOnly);

        ValidateSafety(snapshot);
        ValidateCounts(
            snapshot,
            displayedGateCount,
            displayedQuestionCount,
            displayedTableCount);
        return snapshot;
    }

    private static void ValidateSafety(ResearchMaturitySnapshot snapshot)
    {
        if (!snapshot.ResearchOnly || !snapshot.ReadOnly)
        {
            throw new InvalidDataException(
                "The research-maturity boundary must remain explicitly research-only and read-only.");
        }
        if (snapshot.StrategyChangeRecommendationsAllowed
            || snapshot.Gates.Any(gate => gate.StrategyChangeAllowed))
        {
            throw new InvalidDataException(
                "The research-maturity boundary cannot permit strategy changes.");
        }
        if (!string.Equals(
                snapshot.StrategyOptimizationStatus,
                "LOCKED",
                StringComparison.Ordinal)
            || !string.Equals(
                snapshot.EvidenceGate.StrategyOptimizationStatus,
                "LOCKED",
                StringComparison.Ordinal))
        {
            throw new InvalidDataException(
                "The research-maturity boundary must keep strategy optimization locked.");
        }
    }

    private static void ValidateCounts(
        ResearchMaturitySnapshot snapshot,
        int displayedGateCount,
        int displayedQuestionCount,
        int displayedTableCount)
    {
        ReconcileAlerts(snapshot.MaturityAlerts, "maturity");
        ReconcileAlerts(snapshot.Census.Alerts, "census");
        if (snapshot.EvidenceGate.CompletedAlerts != snapshot.MaturityAlerts.Completed)
        {
            throw new InvalidDataException(
                "The evidence gate does not match the maturity completed-alert count.");
        }
        var expectedGateGap = Math.Max(
            0,
            snapshot.EvidenceGate.RequiredAlerts - snapshot.EvidenceGate.CompletedAlerts);
        if (snapshot.EvidenceNeededToNextGate != expectedGateGap)
        {
            throw new InvalidDataException(
                "The evidence-needed count does not match the current evidence gate.");
        }

        foreach (var gate in snapshot.Gates)
        {
            if (gate.CurrentCompletedAlerts != snapshot.MaturityAlerts.Completed
                || gate.CompletedNeeded
                    != Math.Max(0, gate.RequiredCompletedAlerts - gate.CurrentCompletedAlerts))
            {
                throw new InvalidDataException(
                    $"Research-maturity gate '{gate.Name}' has inconsistent evidence counts.");
            }
        }
        if (snapshot.Census.CompleteEntryPlans + snapshot.Census.IncompleteEntryPlans
            > snapshot.Census.EntryPlans)
        {
            throw new InvalidDataException(
                "Research-maturity census plan counts do not reconcile.");
        }

        ValidateDisplayCount(
            snapshot.GateCount,
            displayedGateCount,
            snapshot.Gates.Count,
            "gate");
        ValidateDisplayCount(
            snapshot.QuestionCount,
            displayedQuestionCount,
            snapshot.Questions.Count,
            "question");
        ValidateDisplayCount(
            snapshot.Census.TableCount,
            displayedTableCount,
            snapshot.Census.TableCounts.Count,
            "table");
        RequireUnique(snapshot.Gates.Select(gate => gate.Name), "gate");
        RequireUnique(snapshot.Questions.Select(question => question.Question), "question");
        RequireUnique(snapshot.Census.TableCounts.Select(table => table.Name), "table");

        if (snapshot.State == ResearchMaturityEvidenceState.Unavailable
            && (snapshot.MaturityAlerts.Total != 0
                || snapshot.Gates.Count != 0
                || snapshot.Census.Captures != 0))
        {
            throw new InvalidDataException(
                "An unavailable research-maturity snapshot cannot contain usable evidence.");
        }
    }

    private static void ReconcileAlerts(
        ResearchMaturityAlertCounts counts,
        string label)
    {
        if (counts.Completed + counts.Pending + counts.Unscorable != counts.Total)
        {
            throw new InvalidDataException(
                $"The research-maturity {label} alert counts do not reconcile.");
        }
    }

    private static void ValidateDisplayCount(
        int fullCount,
        int displayedCount,
        int actualCount,
        string label)
    {
        if (displayedCount != actualCount || displayedCount > fullCount)
        {
            throw new InvalidDataException(
                $"The research-maturity {label} display counts do not reconcile.");
        }
    }

    private static void RequireUnique(IEnumerable<string> values, string label)
    {
        var items = values.ToArray();
        if (items.Distinct(StringComparer.OrdinalIgnoreCase).Count() != items.Length)
        {
            throw new InvalidDataException(
                $"The research-maturity {label} names must be unique.");
        }
    }

    private static ResearchMaturityEvidenceGate EvidenceGate(JsonElement item) => new(
        NonNegativeInteger(item, "completedAlerts"),
        NonNegativeInteger(item, "requiredAlerts"),
        RequiredString(item, "evidenceStatus"),
        RequiredString(item, "allowedAction"),
        RequiredString(item, "strategyOptimizationStatus"),
        RequiredString(item, "reason"));

    private static ResearchMaturityGate Gate(JsonElement item) => new(
        RequiredString(item, "name"),
        RequiredString(item, "status"),
        NonNegativeInteger(item, "currentCompletedAlerts"),
        NonNegativeInteger(item, "requiredCompletedAlerts"),
        NonNegativeInteger(item, "completedNeeded"),
        RequiredString(item, "allowedAction"),
        RequiredBoolean(item, "strategyChangeAllowed"));

    private static ResearchMaturityQuestion Question(JsonElement item) => new(
        RequiredString(item, "question"),
        RequiredString(item, "answer"));

    private static ResearchMaturityTableCount TableCount(JsonElement item) => new(
        RequiredString(item, "name"),
        NonNegativeInteger(item, "count"));

    private static ResearchMaturityEvidenceState State(string value) =>
        value.ToUpperInvariant() switch
        {
            "AVAILABLE" => ResearchMaturityEvidenceState.Available,
            "STALE" => ResearchMaturityEvidenceState.Stale,
            "PARTIAL" => ResearchMaturityEvidenceState.Partial,
            "EMPTY" => ResearchMaturityEvidenceState.Empty,
            "UNAVAILABLE" => ResearchMaturityEvidenceState.Unavailable,
            _ => throw new InvalidDataException(
                $"Unknown research-maturity evidence state: {value}."),
        };

    private static int NonNegativeInteger(JsonElement item, string name)
    {
        var value = RequiredInteger(item, name);
        return value >= 0
            ? value
            : throw new InvalidDataException(
                $"Research-maturity '{name}' cannot be negative.");
    }

    private static int RequiredInteger(JsonElement item, string name) =>
        Property(item, name, out var value)
        && value.ValueKind == JsonValueKind.Number
        && value.TryGetInt32(out var number)
            ? number
            : throw new InvalidDataException(
                $"The research-maturity snapshot is missing integer '{name}'.");

    private static decimal? OptionalPercentage(JsonElement item, string name)
    {
        if (!Property(item, name, out var value) || value.ValueKind == JsonValueKind.Null)
        {
            return null;
        }
        if (value.ValueKind != JsonValueKind.Number
            || !value.TryGetDecimal(out var number)
            || number < 0m
            || number > 100m)
        {
            throw new InvalidDataException(
                $"Research-maturity '{name}' must be null or between 0 and 100.");
        }
        return number;
    }

    private static bool RequiredBoolean(JsonElement item, string name) =>
        Property(item, name, out var value)
        && value.ValueKind is JsonValueKind.True or JsonValueKind.False
            ? value.GetBoolean()
            : throw new InvalidDataException(
                $"The research-maturity snapshot is missing boolean '{name}'.");

    private static string RequiredString(JsonElement item, string name) =>
        Property(item, name, out var value)
        && value.ValueKind == JsonValueKind.String
        && value.GetString()?.Trim() is { Length: > 0 } text
            ? text
            : throw new InvalidDataException(
                $"The research-maturity snapshot is missing '{name}'.");

    private static IReadOnlyList<string> RequiredStringArray(
        JsonElement item,
        string name) =>
        RequiredArray(item, name)
            .Select((value, index) =>
                value.ValueKind == JsonValueKind.String
                && value.GetString()?.Trim() is { Length: > 0 } text
                    ? text
                    : throw new InvalidDataException(
                        $"Research-maturity '{name}[{index}]' must be non-empty text."))
            .ToArray();

    private static DateTimeOffset RequiredTimestamp(JsonElement item, string name) =>
        DateTimeOffset.TryParse(
            RequiredString(item, name),
            CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal,
            out var value)
            ? value
            : throw new InvalidDataException(
                $"The research-maturity snapshot has an invalid '{name}' timestamp.");

    private static DateTimeOffset? OptionalTimestamp(JsonElement item, string name)
    {
        if (!Property(item, name, out var value) || value.ValueKind == JsonValueKind.Null)
        {
            return null;
        }
        if (value.ValueKind != JsonValueKind.String
            || !DateTimeOffset.TryParse(
                value.GetString(),
                CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal,
                out var timestamp))
        {
            throw new InvalidDataException(
                $"The research-maturity snapshot has an invalid '{name}' timestamp.");
        }
        return timestamp;
    }

    private static JsonElement RequiredObject(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.Object
            ? value
            : throw new InvalidDataException(
                $"The research-maturity snapshot is missing object '{name}'.");

    private static IReadOnlyList<JsonElement> RequiredArray(
        JsonElement item,
        string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.Array
            ? value.EnumerateArray().ToArray()
            : throw new InvalidDataException(
                $"The research-maturity snapshot is missing array '{name}'.");

    private static void RequireObject(JsonElement item, string message)
    {
        if (item.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException(message);
        }
    }

    private static bool Property(
        JsonElement item,
        string name,
        out JsonElement value)
    {
        value = default;
        return item.ValueKind == JsonValueKind.Object
            && item.TryGetProperty(name, out value)
            && value.ValueKind is not JsonValueKind.Undefined;
    }
}
