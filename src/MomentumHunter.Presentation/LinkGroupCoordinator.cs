using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed class LinkGroupCoordinator
{
    private readonly PaneRegistry _registry;

    public LinkGroupCoordinator(PaneRegistry registry)
    {
        _registry = registry;
    }

    public void PublishSymbol(LinkGroup linkGroup, string symbol, string interval)
    {
        if (linkGroup == LinkGroup.Unlinked)
        {
            return;
        }

        foreach (var pane in _registry.Panes.Where(pane =>
                     !pane.IsPinned &&
                     pane.LinkGroup == linkGroup &&
                     pane.Kind is PaneKind.Hunter
                         or PaneKind.Chart
                         or PaneKind.TradePlan
                         or PaneKind.Research
                         or PaneKind.CandidateStory))
        {
            pane.Symbol = symbol;
            pane.Interval = interval;
        }
    }
}
