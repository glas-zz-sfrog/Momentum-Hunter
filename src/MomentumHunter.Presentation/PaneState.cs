using CommunityToolkit.Mvvm.ComponentModel;
using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed partial class PaneState : ObservableObject
{
    public PaneState(
        PaneKind kind,
        string title,
        LinkGroup linkGroup,
        DockRegion dockRegion,
        string symbol,
        string interval,
        int sortOrder,
        Guid? instanceId = null)
    {
        InstanceId = instanceId ?? Guid.NewGuid();
        Kind = kind;
        Title = title;
        LinkGroup = linkGroup;
        DockRegion = dockRegion;
        Symbol = symbol;
        Interval = interval;
        SortOrder = sortOrder;
    }

    public Guid InstanceId { get; }

    public PaneKind Kind { get; }

    [ObservableProperty]
    private string _title;

    [ObservableProperty]
    private LinkGroup _linkGroup;

    [ObservableProperty]
    private string _symbol;

    [ObservableProperty]
    private string _interval;

    [ObservableProperty]
    private bool _isPinned;

    [ObservableProperty]
    private bool _isVisible = true;

    public string VisibilityLabel => IsVisible ? "Visible" : "Hidden";

    public string VisibilityActionLabel => IsVisible ? "Focus" : "Open";

    [ObservableProperty]
    private DockRegion _dockRegion;

    [ObservableProperty]
    private int _sortOrder;

    [ObservableProperty]
    private string? _displayKey;

    [ObservableProperty]
    private RectGeometry? _floatingBounds;

    [ObservableProperty]
    private string? _softClosedDockLayoutXml;

    public PaneLayout ToLayout() => new(
        InstanceId,
        Kind,
        Title,
        LinkGroup,
        Symbol,
        Interval,
        IsPinned,
        IsVisible,
        DockRegion,
        SortOrder,
        DisplayKey,
        FloatingBounds,
        SoftClosedDockLayoutXml);

    public static PaneState FromLayout(PaneLayout layout) => new(
        layout.Kind,
        layout.Title,
        layout.LinkGroup,
        layout.DockRegion,
        layout.Symbol,
        layout.Interval,
        layout.SortOrder,
        layout.InstanceId)
    {
        IsPinned = layout.IsPinned,
        IsVisible = layout.IsVisible,
        DisplayKey = layout.DisplayKey,
        FloatingBounds = layout.FloatingBounds,
        SoftClosedDockLayoutXml = layout.SoftClosedDockLayoutXml,
    };

    partial void OnIsVisibleChanged(bool value)
    {
        OnPropertyChanged(nameof(VisibilityLabel));
        OnPropertyChanged(nameof(VisibilityActionLabel));
    }
}
