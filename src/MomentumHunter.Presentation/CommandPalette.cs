using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public enum CommandPaletteAction
{
    OpenCandidate,
    AddChart,
    ToggleActivity,
    ViewDiagnostics,
}

public sealed record CommandPaletteItem(
    string Id,
    CommandPaletteAction Action,
    string Title,
    string Detail,
    string? Symbol = null);

public sealed record CommandPaletteExecution(
    bool Executed,
    CommandPaletteAction? Action = null,
    PaneState? AddedPane = null);

public static class CommandPaletteCatalog
{
    private sealed record StaticCommand(
        string Id,
        CommandPaletteAction Action,
        string Title,
        string Detail,
        IReadOnlyList<string> SearchTerms);

    private static readonly IReadOnlyList<StaticCommand> StaticCommands =
    [
        new(
            "add-chart",
            CommandPaletteAction.AddChart,
            "Add chart",
            "Open a linked chart for the selected symbol.",
            ["add chart", "new chart", "chart"]),
        new(
            "toggle-activity",
            CommandPaletteAction.ToggleActivity,
            "Toggle activity",
            "Show or hide the workstation activity pane.",
            ["toggle activity", "activity", "events"]),
        new(
            "view-diagnostics",
            CommandPaletteAction.ViewDiagnostics,
            "View diagnostics",
            "Open the workstation diagnostics pane.",
            ["view diagnostics", "diagnostics", "system diagnostics"]),
    ];

    public static IReadOnlyList<CommandPaletteItem> Filter(
        IEnumerable<CandidateSnapshot> candidates,
        string? query,
        int limit = 12)
    {
        ArgumentNullException.ThrowIfNull(candidates);
        if (limit < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(limit), limit, "The result limit must be positive.");
        }

        var candidateArray = candidates.ToArray();
        var normalized = Normalize(query);
        var candidateItems = CandidateMatches(candidateArray, normalized);
        var commandItems = StaticCommands
            .Where(command => normalized.Length == 0 || Matches(command, normalized))
            .Select(ToItem);

        return (normalized.Length == 0
                ? commandItems.Concat(candidateItems.Take(5))
                : candidateItems.Concat(commandItems))
            .Take(limit)
            .ToArray();
    }

    public static CommandPaletteItem? FindExact(
        IEnumerable<CandidateSnapshot> candidates,
        string? query)
    {
        ArgumentNullException.ThrowIfNull(candidates);
        var normalized = Normalize(query);
        if (normalized.Length == 0)
        {
            return null;
        }

        var candidate = candidates.FirstOrDefault(item =>
            string.Equals(item.Symbol, normalized, StringComparison.OrdinalIgnoreCase));
        if (candidate is not null)
        {
            return ToItem(candidate);
        }

        var command = StaticCommands.FirstOrDefault(item =>
            item.SearchTerms.Any(term => string.Equals(term, normalized, StringComparison.OrdinalIgnoreCase)));
        return command is null ? null : ToItem(command);
    }

    private static IEnumerable<CommandPaletteItem> CandidateMatches(
        IReadOnlyList<CandidateSnapshot> candidates,
        string normalized)
    {
        var matches = normalized.Length == 0
            ? candidates
            : candidates.Where(candidate =>
                candidate.Symbol.Contains(normalized, StringComparison.OrdinalIgnoreCase) ||
                candidate.Company.Contains(normalized, StringComparison.OrdinalIgnoreCase));

        return matches
            .OrderBy(candidate =>
                string.Equals(candidate.Symbol, normalized, StringComparison.OrdinalIgnoreCase) ? 0 :
                candidate.Symbol.StartsWith(normalized, StringComparison.OrdinalIgnoreCase) ? 1 :
                2)
            .ThenByDescending(candidate => candidate.Score)
            .ThenBy(candidate => candidate.Symbol, StringComparer.OrdinalIgnoreCase)
            .Select(ToItem);
    }

    private static bool Matches(StaticCommand command, string normalized) =>
        command.SearchTerms.Any(term =>
            term.Contains(normalized, StringComparison.OrdinalIgnoreCase) ||
            normalized.Contains(term, StringComparison.OrdinalIgnoreCase));

    private static CommandPaletteItem ToItem(CandidateSnapshot candidate) =>
        new(
            $"candidate:{candidate.Symbol.ToUpperInvariant()}",
            CommandPaletteAction.OpenCandidate,
            $"{candidate.Symbol.ToUpperInvariant()}  {candidate.Company}",
            $"Open candidate  |  Score {candidate.Score}  |  {candidate.OperatorState}",
            candidate.Symbol);

    private static CommandPaletteItem ToItem(StaticCommand command) =>
        new(command.Id, command.Action, command.Title, command.Detail);

    private static string Normalize(string? query) => query?.Trim() ?? string.Empty;
}
