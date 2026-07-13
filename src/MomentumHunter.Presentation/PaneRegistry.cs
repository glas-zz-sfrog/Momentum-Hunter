using System.Collections.ObjectModel;
using System.ComponentModel;
using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed class PaneRegistry
{
    private readonly ObservableCollection<PaneState> _panes = [];

    public ReadOnlyObservableCollection<PaneState> Panes { get; }

    public event EventHandler? Changed;

    public PaneRegistry()
    {
        Panes = new ReadOnlyObservableCollection<PaneState>(_panes);
    }

    public PaneState Create(
        PaneKind kind,
        string title,
        LinkGroup linkGroup = LinkGroup.Unlinked,
        DockRegion dockRegion = DockRegion.Center,
        string symbol = "NVDA",
        string interval = "5m")
    {
        var nextSort = _panes.Count == 0 ? 0 : _panes.Max(pane => pane.SortOrder) + 1;
        var pane = new PaneState(kind, title, linkGroup, dockRegion, symbol, interval, nextSort);
        _panes.Add(pane);
        Subscribe(pane);
        OnChanged();
        return pane;
    }

    public bool SoftClose(Guid instanceId)
    {
        var pane = Find(instanceId);
        if (pane is null || !pane.IsVisible)
        {
            return false;
        }

        pane.IsVisible = false;
        return true;
    }

    public bool Reopen(Guid instanceId)
    {
        var pane = Find(instanceId);
        if (pane is null || pane.IsVisible)
        {
            return false;
        }

        pane.IsVisible = true;
        return true;
    }

    public bool Remove(Guid instanceId)
    {
        var pane = Find(instanceId);
        if (pane is null)
        {
            return false;
        }

        _panes.Remove(pane);
        Unsubscribe(pane);
        OnChanged();
        return true;
    }

    public PaneState? Find(Guid instanceId) => _panes.FirstOrDefault(pane => pane.InstanceId == instanceId);

    public IReadOnlyList<PaneLayout> ToLayouts() => _panes
        .OrderBy(pane => pane.SortOrder)
        .Select(pane => pane.ToLayout())
        .ToArray();

    public void Restore(IEnumerable<PaneLayout> layouts)
    {
        foreach (var pane in _panes)
        {
            Unsubscribe(pane);
        }

        _panes.Clear();
        foreach (var layout in layouts.OrderBy(layout => layout.SortOrder))
        {
            var pane = PaneState.FromLayout(layout);
            _panes.Add(pane);
            Subscribe(pane);
        }

        OnChanged();
    }

    private void Subscribe(PaneState pane) => pane.PropertyChanged += OnPanePropertyChanged;

    private void Unsubscribe(PaneState pane) => pane.PropertyChanged -= OnPanePropertyChanged;

    private void OnPanePropertyChanged(object? sender, PropertyChangedEventArgs e) => OnChanged();

    private void OnChanged() => Changed?.Invoke(this, EventArgs.Empty);
}
