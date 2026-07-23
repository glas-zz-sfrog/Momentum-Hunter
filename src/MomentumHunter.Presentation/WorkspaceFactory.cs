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
                registry.Create(PaneKind.ReviewOutcomes, "Outcomes", LinkGroup.Unlinked, DockRegion.Bottom, symbol, interval).IsVisible = false;
                registry.Create(PaneKind.Diagnostics, "Diagnostics", LinkGroup.Unlinked, DockRegion.Bottom, symbol, interval).IsVisible = false;
                break;
            default:
                throw new ArgumentOutOfRangeException(nameof(workspace), workspace, null);
        }

        return registry;
    }
}
