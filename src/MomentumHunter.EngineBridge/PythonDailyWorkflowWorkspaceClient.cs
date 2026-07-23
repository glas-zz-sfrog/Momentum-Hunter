using System.Globalization;
using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.EngineBridge;

public sealed class PythonDailyWorkflowWorkspaceClient : IDailyWorkflowWorkspaceClient
{
    private readonly IPythonEngineHostConnection _connection;

    public PythonDailyWorkflowWorkspaceClient(IPythonEngineHostConnection connection)
    {
        _connection = connection;
    }

    public async Task<DailyWorkflowSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
        PythonDailyWorkflowSnapshotMapper.Map(
            await _connection.GetDailyWorkflowSnapshotAsync(cancellationToken));
}

public static class PythonDailyWorkflowSnapshotMapper
{
    private static readonly string[] ExpectedStepIds = ["capture", "review", "plans", "report", "readiness"];

    public static DailyWorkflowSnapshot Map(JsonElement root)
    {
        RequireObject(root, "The Python Daily Workflow snapshot must be a JSON object.");
        var schemaVersion = RequiredInteger(root, "schemaVersion");
        if (schemaVersion != 1)
        {
            throw new InvalidDataException($"Unsupported Python Daily Workflow schema version: {schemaVersion}.");
        }

        var state = State(RequiredString(root, "state"));
        var observedAt = RequiredTimestamp(root, "observedAt");
        var sourceAsOf = OptionalTimestamp(root, "sourceAsOf");
        var review = ReviewCounts(RequiredObject(root, "review"));
        var plans = PlanCounts(RequiredObject(root, "plans"));
        var outcomes = OutcomeCounts(RequiredObject(root, "outcomes"));
        var readiness = RequiredArray(root, "readiness").Select(ReadinessGate).ToArray();
        var nextAction = NextAction(RequiredObject(root, "nextAction"));
        var steps = RequiredArray(root, "steps").Select(Step).ToArray();
        var warnings = RequiredArray(root, "warnings")
            .Select((item, index) => RequiredArrayString(item, $"warnings[{index}]"))
            .ToArray();
        var readOnly = RequiredBoolean(root, "readOnly");
        if (!readOnly)
        {
            throw new InvalidDataException("The Daily Workflow boundary must remain read-only.");
        }

        ValidateCounts(review, plans);
        ValidateCollections(state, review, readiness, steps);
        return new DailyWorkflowSnapshot(
            schemaVersion,
            state,
            observedAt,
            sourceAsOf,
            RequiredString(root, "sourceLabel"),
            RequiredString(root, "sourceContext"),
            RequiredString(root, "operatorContextState"),
            RequiredString(root, "operatorContextLabel"),
            RequiredString(root, "summary"),
            BoundedInteger(root, "workflowScore", 0, 100),
            RequiredString(root, "captureStatus"),
            review,
            plans,
            outcomes,
            readiness,
            nextAction,
            steps,
            warnings,
            readOnly);
    }

    private static DailyWorkflowReviewCounts ReviewCounts(JsonElement item) => new(
        NonNegativeInteger(item, "total"),
        NonNegativeInteger(item, "reviewed"),
        NonNegativeInteger(item, "unreviewed"),
        NonNegativeInteger(item, "interested"),
        NonNegativeInteger(item, "rejected"),
        NonNegativeInteger(item, "watchlist"));

    private static DailyWorkflowPlanCounts PlanCounts(JsonElement item) => new(
        NonNegativeInteger(item, "watchlist"),
        NonNegativeInteger(item, "complete"),
        NonNegativeInteger(item, "incomplete"),
        NonNegativeInteger(item, "missingTrigger"),
        NonNegativeInteger(item, "missingStop"),
        NonNegativeInteger(item, "missingInvalidation"),
        NonNegativeInteger(item, "missingMaxLoss"),
        NonNegativeInteger(item, "withoutPlan"));

    private static DailyWorkflowOutcomeCounts OutcomeCounts(JsonElement item) => new(
        NonNegativeInteger(item, "completedNextDay"),
        NonNegativeInteger(item, "completedFiveDay"),
        NonNegativeInteger(item, "pending"));

    private static DailyWorkflowReadinessGate ReadinessGate(JsonElement item)
    {
        RequireObject(item, "Each Daily Workflow readiness gate must be an object.");
        return new DailyWorkflowReadinessGate(
            RequiredString(item, "name"),
            RequiredString(item, "status"));
    }

    private static DailyWorkflowNextAction NextAction(JsonElement item) => new(
        RequiredString(item, "title"),
        RequiredString(item, "detail"),
        Level(RequiredString(item, "level")));

    private static DailyWorkflowStepSnapshot Step(JsonElement item)
    {
        RequireObject(item, "Each Daily Workflow step must be an object.");
        return new DailyWorkflowStepSnapshot(
            RequiredString(item, "id"),
            RequiredString(item, "name"),
            Level(RequiredString(item, "level")),
            RequiredString(item, "status"),
            Light(RequiredString(item, "light")),
            RequiredString(item, "dependency"),
            RequiredString(item, "blocker"),
            RequiredString(item, "detail"));
    }

    private static void ValidateCounts(
        DailyWorkflowReviewCounts review,
        DailyWorkflowPlanCounts plans)
    {
        if (review.Reviewed + review.Unreviewed != review.Total)
        {
            throw new InvalidDataException("Daily Workflow reviewed and unreviewed counts must equal the candidate total.");
        }
        if (review.Interested + review.Rejected + review.Watchlist != review.Reviewed)
        {
            throw new InvalidDataException("Daily Workflow decision counts must equal the reviewed count.");
        }
        if (plans.Watchlist != review.Watchlist)
        {
            throw new InvalidDataException("Daily Workflow review and plan watchlist counts must match.");
        }
        if (plans.Complete + plans.Incomplete != plans.Watchlist)
        {
            throw new InvalidDataException("Daily Workflow complete and incomplete plan counts must equal the watchlist count.");
        }
        if (new[]
            {
                plans.MissingTrigger,
                plans.MissingStop,
                plans.MissingInvalidation,
                plans.MissingMaxLoss,
                plans.WithoutPlan,
            }.Any(count => count > plans.Incomplete))
        {
            throw new InvalidDataException("Daily Workflow missing-plan counts cannot exceed incomplete plans.");
        }
    }

    private static void ValidateCollections(
        DailyWorkflowEvidenceState state,
        DailyWorkflowReviewCounts review,
        IReadOnlyList<DailyWorkflowReadinessGate> readiness,
        IReadOnlyList<DailyWorkflowStepSnapshot> steps)
    {
        if (readiness.Select(item => item.Name).Distinct(StringComparer.OrdinalIgnoreCase).Count() != readiness.Count)
        {
            throw new InvalidDataException("Daily Workflow readiness names must be unique.");
        }
        if (state == DailyWorkflowEvidenceState.Unavailable)
        {
            if (review.Total != 0 || steps.Count != 0)
            {
                throw new InvalidDataException("An unavailable Daily Workflow snapshot cannot contain candidates or steps.");
            }
            return;
        }
        if (state == DailyWorkflowEvidenceState.Empty && review.Total != 0)
        {
            throw new InvalidDataException("An empty Daily Workflow snapshot cannot contain candidates.");
        }
        if (steps.Count != ExpectedStepIds.Length
            || !steps.Select(step => step.Id).SequenceEqual(ExpectedStepIds, StringComparer.Ordinal))
        {
            throw new InvalidDataException("Daily Workflow steps must contain the canonical five-step sequence.");
        }
    }

    private static DailyWorkflowEvidenceState State(string value) => value.ToUpperInvariant() switch
    {
        "AVAILABLE" => DailyWorkflowEvidenceState.Available,
        "STALE" => DailyWorkflowEvidenceState.Stale,
        "PARTIAL" => DailyWorkflowEvidenceState.Partial,
        "EMPTY" => DailyWorkflowEvidenceState.Empty,
        "UNAVAILABLE" => DailyWorkflowEvidenceState.Unavailable,
        _ => throw new InvalidDataException($"Unknown Daily Workflow evidence state: {value}."),
    };

    private static DailyWorkflowStepLevel Level(string value) => value.ToLowerInvariant() switch
    {
        "complete" => DailyWorkflowStepLevel.Complete,
        "active" => DailyWorkflowStepLevel.Active,
        "attention" => DailyWorkflowStepLevel.Attention,
        "blocked" => DailyWorkflowStepLevel.Blocked,
        "waiting" => DailyWorkflowStepLevel.Waiting,
        "locked" => DailyWorkflowStepLevel.Locked,
        _ => throw new InvalidDataException($"Unknown Daily Workflow step level: {value}."),
    };

    private static DailyWorkflowLight Light(string value) => value.ToLowerInvariant() switch
    {
        "green" => DailyWorkflowLight.Green,
        "blue" => DailyWorkflowLight.Blue,
        "yellow" => DailyWorkflowLight.Yellow,
        "red" => DailyWorkflowLight.Red,
        "gray" => DailyWorkflowLight.Gray,
        _ => throw new InvalidDataException($"Unknown Daily Workflow light: {value}."),
    };

    private static int NonNegativeInteger(JsonElement item, string name) =>
        BoundedInteger(item, name, 0, int.MaxValue);

    private static int BoundedInteger(JsonElement item, string name, int minimum, int maximum)
    {
        var value = RequiredInteger(item, name);
        return value >= minimum && value <= maximum
            ? value
            : throw new InvalidDataException($"Daily Workflow '{name}' must be between {minimum} and {maximum}.");
    }

    private static int RequiredInteger(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number)
            ? number
            : throw new InvalidDataException($"The Daily Workflow snapshot is missing integer '{name}'.");

    private static bool RequiredBoolean(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind is JsonValueKind.True or JsonValueKind.False
            ? value.GetBoolean()
            : throw new InvalidDataException($"The Daily Workflow snapshot is missing boolean '{name}'.");

    private static string RequiredString(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.String
            && value.GetString()?.Trim() is { Length: > 0 } text
            ? text
            : throw new InvalidDataException($"The Daily Workflow snapshot is missing '{name}'.");

    private static string RequiredArrayString(JsonElement item, string name) =>
        item.ValueKind == JsonValueKind.String && item.GetString()?.Trim() is { Length: > 0 } text
            ? text
            : throw new InvalidDataException($"The Daily Workflow snapshot contains invalid '{name}'.");

    private static DateTimeOffset RequiredTimestamp(JsonElement item, string name) =>
        DateTimeOffset.TryParse(
            RequiredString(item, name),
            CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal,
            out var value)
            ? value
            : throw new InvalidDataException($"The Daily Workflow snapshot has an invalid '{name}' timestamp.");

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
            throw new InvalidDataException($"The Daily Workflow snapshot has an invalid '{name}' timestamp.");
        }
        return timestamp;
    }

    private static JsonElement RequiredObject(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.Object
            ? value
            : throw new InvalidDataException($"The Daily Workflow snapshot is missing object '{name}'.");

    private static IReadOnlyList<JsonElement> RequiredArray(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.Array
            ? value.EnumerateArray().ToArray()
            : throw new InvalidDataException($"The Daily Workflow snapshot is missing array '{name}'.");

    private static void RequireObject(JsonElement item, string message)
    {
        if (item.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException(message);
        }
    }

    private static bool Property(JsonElement item, string name, out JsonElement value)
    {
        value = default;
        return item.ValueKind == JsonValueKind.Object
            && item.TryGetProperty(name, out value)
            && value.ValueKind is not JsonValueKind.Undefined;
    }
}
