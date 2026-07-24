using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public static class WorkspaceFactory
{
    public static PaneRegistry Create(WorkspaceKind workspace, string symbol = "NVDA", string interval = "5m")
    {
        var registry = new PaneRegistry();
        switch (workspace)
        {
            case WorkspaceKind.Live:
                registry.Create(PaneKind.Hunter, "Hunter", LinkGroup.A, DockRegion.Left, symbol, interval);
                registry.Create(PaneKind.Chart, "Chart", LinkGroup.A, DockRegion.Center, symbol, interval);
                registry.Create(PaneKind.TradePlan, "Trade Plan", LinkGroup.A, DockRegion.Right, symbol, interval);
                registry.Create(PaneKind.Activity, "Activity", LinkGroup.Unlinked, DockRegion.Bottom, symbol, interval).IsVisible = false;
                registry.Create(PaneKind.Research, "Research", LinkGroup.A, DockRegion.Bottom, symbol, interval).IsVisible = false;
                registry.Create(PaneKind.Watchlist, "Watchlist", LinkGroup.Unlinked, DockRegion.Left, symbol, interval).IsVisible = false;
                registry.Create(PaneKind.DailyWorkflow, "Daily Workflow", LinkGroup.Unlinked, DockRegion.Bottom, symbol, interval).IsVisible = false;
                registry.Create(PaneKind.CandidateStory, "Candidate Story", LinkGroup.A, DockRegion.Bottom, symbol, interval).IsVisible = false;
                registry.Create(PaneKind.ResearchMaturity, "Research Maturity", LinkGroup.Unlinked, DockRegion.Bottom, symbol, interval).IsVisible = false;
                registry.Create(PaneKind.Automation, "Automation", LinkGroup.Unlinked, DockRegion.Bottom, symbol, interval).IsVisible = false;
                registry.Create(PaneKind.Orders, "Orders", LinkGroup.Unlinked, DockRegion.Bottom, symbol, interval).IsVisible = false;
                registry.Create(PaneKind.Positions, "Positions", LinkGroup.Unlinked, DockRegion.Bottom, symbol, interval).IsVisible = false;
                registry.Create(PaneKind.Diagnostics, "Diagnostics", LinkGroup.Unlinked, DockRegion.Bottom, symbol, interval).IsVisible = false;
                break;
            case WorkspaceKind.Replay:
                registry.Create(PaneKind.Hunter, "Replay Timeline", LinkGroup.A, DockRegion.Left, symbol, interval);
                registry.Create(PaneKind.Chart, "Chart", LinkGroup.A, DockRegion.Center, symbol, interval);
                registry.Create(PaneKind.TradePlan, "Plan Snapshot", LinkGroup.A, DockRegion.Right, symbol, interval);
                registry.Create(PaneKind.ReplayEvents, "Replay Events", LinkGroup.Unlinked, DockRegion.Bottom, symbol, interval).IsVisible = false;
                registry.Create(PaneKind.Diagnostics, "Diagnostics", LinkGroup.Unlinked, DockRegion.Bottom, symbol, interval).IsVisible = false;
                break;
            case WorkspaceKind.Review:
                registry.Create(PaneKind.Hunter, "Outcome Explorer", LinkGroup.A, DockRegion.Left, symbol, interval);
                registry.Create(PaneKind.Chart, "Review Chart", LinkGroup.A, DockRegion.Center, symbol, interval);
                registry.Create(PaneKind.TradePlan, "Audit Detail", LinkGroup.A, DockRegion.Right, symbol, interval);
                registry.Create(PaneKind.ShadowReview, "Test Trade Review", LinkGroup.A, DockRegion.Bottom, symbol, interval);
                registry.Create(PaneKind.ReviewOutcomes, "Outcomes", LinkGroup.Unlinked, DockRegion.Bottom, symbol, interval).IsVisible = false;
                registry.Create(PaneKind.Diagnostics, "Diagnostics", LinkGroup.Unlinked, DockRegion.Bottom, symbol, interval).IsVisible = false;
                break;
            default:
                throw new ArgumentOutOfRangeException(nameof(workspace), workspace, null);
        }

        return registry;
    }

    public static void EnsureStandardPanes(
        PaneRegistry registry,
        WorkspaceKind workspace,
        string symbol,
        string interval)
    {
        var defaults = Create(workspace, symbol, interval);
        foreach (var defaultPane in defaults.Panes)
        {
            var existing = registry.Panes.FirstOrDefault(pane => pane.Kind == defaultPane.Kind);
            if (existing is not null)
            {
                if (existing.Kind == PaneKind.ShadowReview
                    && string.Equals(existing.Title, "Shadow Review", StringComparison.Ordinal))
                {
                    existing.Title = defaultPane.Title;
                }

                continue;
            }

            var restored = registry.Create(
                defaultPane.Kind,
                defaultPane.Title,
                defaultPane.LinkGroup,
                defaultPane.DockRegion,
                symbol,
                interval);
            restored.IsVisible = defaultPane.IsVisible;
        }
    }
}
