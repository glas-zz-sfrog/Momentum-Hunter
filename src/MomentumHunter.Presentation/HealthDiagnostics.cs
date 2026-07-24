using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed record HealthDiagnosticComponentView(
    string Name,
    HealthState State,
    string StateLabel,
    string Summary,
    string CheckedAtLabel);

public sealed record HealthDiagnosticsView(
    string StatusLabel,
    string Summary,
    string CheckedAtLabel,
    IReadOnlyList<HealthDiagnosticComponentView> Components)
{
    public static HealthDiagnosticsView From(SystemHealthSnapshot? snapshot)
    {
        if (snapshot is null)
        {
            return new HealthDiagnosticsView(
                "UNAVAILABLE",
                "No system health snapshot is available.",
                "Snapshot time unavailable",
                []);
        }

        var components = snapshot.Components
            .Select(component => new HealthDiagnosticComponentView(
                TextOrFallback(component.Name, "Unnamed health component"),
                component.State,
                component.State.ToString().ToUpperInvariant(),
                TextOrFallback(component.Summary, "No diagnostic summary was supplied."),
                $"Checked {component.CheckedAt.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC"))
            .ToArray();
        if (components.Length == 0)
        {
            return new HealthDiagnosticsView(
                "UNAVAILABLE",
                "The system health snapshot contains no component diagnostics.",
                $"Snapshot checked {snapshot.CheckedAt.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC",
                components);
        }

        var healthyCount = components.Count(component => component.State == HealthState.Healthy);
        var degradedCount = components.Count(component => component.State == HealthState.Degraded);
        var unavailableCount = components.Count(component => component.State == HealthState.Unavailable);
        var status = degradedCount > 0
            ? "DEGRADED"
            : unavailableCount > 0
                ? "PARTIAL"
                : "HEALTHY";

        return new HealthDiagnosticsView(
            status,
            $"{components.Length} components | {healthyCount} healthy | {degradedCount} degraded | {unavailableCount} unavailable",
            $"Snapshot checked {snapshot.CheckedAt.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC",
            components);
    }

    private static string TextOrFallback(string? value, string fallback) =>
        string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
}
