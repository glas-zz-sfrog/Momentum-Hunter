using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

/// <summary>
/// Holds the display context for one chart instance. Each pane owns a copied
/// candle collection so a linked selection in another group cannot repaint it.
/// </summary>
public sealed class ChartPaneViewModel : ObservableObject
{
    private CandleSnapshot? _inspectedBar;

    public ChartPaneViewModel(PaneState pane, IEnumerable<CandleSnapshot> candles)
        : this(
            pane,
            new ChartSnapshot(
                1,
                pane.Symbol,
                pane.Interval,
                ChartDataState.Available,
                DateTimeOffset.UtcNow,
                DateTimeOffset.UtcNow,
                "Local deterministic simulation candles.",
                new DataLineage("Local simulation", DateTimeOffset.UtcNow, "Deterministic local shell data."),
                candles.ToArray()))
    {
    }

    public ChartPaneViewModel(PaneState pane, ChartSnapshot snapshot)
    {
        Pane = pane;
        Candles = new ObservableCollection<CandleSnapshot>();
        ApplySnapshot(snapshot);
        Pane.PropertyChanged += OnPanePropertyChanged;
    }

    public PaneState Pane { get; }

    public ObservableCollection<CandleSnapshot> Candles { get; }

    public ChartDataState DataState { get; private set; }

    public DataLineage? DataLineage { get; private set; }

    public string SourceSummary { get; private set; } = "Chart evidence unavailable.";

    public bool PreviewOnly { get; private set; }

    public bool ActiveChartSource { get; private set; } = true;

    public string EmptyStateText => DataState switch
    {
        ChartDataState.InsufficientData when PreviewOnly => "Insufficient staged preview candles",
        ChartDataState.Unavailable when PreviewOnly => "No staged preview candles available",
        ChartDataState.InsufficientData => "Insufficient stored candles",
        ChartDataState.Unavailable => "No stored candles available",
        _ => "No deterministic candles available",
    };

    public string Title => $"Chart {Pane.LinkGroup}  |  {Pane.Symbol}";

    public string ContextLabel => Pane.IsPinned
        ? "Pinned chart context"
        : $"Link {Pane.LinkGroup} chart context";

    public string DetailLabel => $"{ContextLabel} | {SourceSummary}";

    public CandleSnapshot? LatestBar { get; private set; }

    public string LatestBarSummary => LatestBar is null
        ? "Latest bar unavailable"
        : FormatBar(LatestBar);

    public CandleSnapshot? InspectedBar
    {
        get => _inspectedBar;
        set
        {
            if (!SetProperty(ref _inspectedBar, value))
            {
                return;
            }

            OnPropertyChanged(nameof(ActiveBarLabel));
            OnPropertyChanged(nameof(ActiveBarSummary));
        }
    }

    public string ActiveBarLabel => InspectedBar is null
        ? "LATEST BAR"
        : "INSPECTED BAR";

    public string ActiveBarSummary => InspectedBar is null
        ? LatestBarSummary
        : FormatBar(InspectedBar);

    public void ReplaceCandles(IEnumerable<CandleSnapshot> candles)
    {
        InspectedBar = null;
        Candles.Clear();
        foreach (var candle in candles)
        {
            Candles.Add(candle);
        }

        LatestBar = Candles
            .OrderBy(candle => candle.Timestamp)
            .LastOrDefault();
        OnPropertyChanged(nameof(LatestBar));
        OnPropertyChanged(nameof(LatestBarSummary));
        OnPropertyChanged(nameof(ActiveBarSummary));
    }

    public void ApplySnapshot(ChartSnapshot snapshot)
    {
        DataState = snapshot.State;
        DataLineage = snapshot.DataLineage;
        SourceSummary = snapshot.Summary;
        PreviewOnly = snapshot.PreviewOnly;
        ActiveChartSource = snapshot.ActiveChartSource;
        ReplaceCandles(snapshot.Candles);
        OnPropertyChanged(nameof(DataState));
        OnPropertyChanged(nameof(DataLineage));
        OnPropertyChanged(nameof(SourceSummary));
        OnPropertyChanged(nameof(PreviewOnly));
        OnPropertyChanged(nameof(ActiveChartSource));
        OnPropertyChanged(nameof(EmptyStateText));
        OnPropertyChanged(nameof(DetailLabel));
    }

    private void OnPanePropertyChanged(object? sender, PropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.PropertyName is nameof(PaneState.Symbol) or nameof(PaneState.Interval) or nameof(PaneState.LinkGroup))
        {
            OnPropertyChanged(nameof(Title));
        }

        if (eventArgs.PropertyName is nameof(PaneState.Interval))
        {
            OnPropertyChanged(nameof(LatestBarSummary));
            OnPropertyChanged(nameof(ActiveBarSummary));
        }

        if (eventArgs.PropertyName is nameof(PaneState.IsPinned) or nameof(PaneState.LinkGroup))
        {
            OnPropertyChanged(nameof(ContextLabel));
            OnPropertyChanged(nameof(DetailLabel));
        }
    }

    private string FormatTimestamp(DateTimeOffset timestamp)
    {
        var format = string.Equals(Pane.Interval, "Daily", StringComparison.OrdinalIgnoreCase)
            ? "yyyy-MM-dd 'UTC'"
            : "yyyy-MM-dd HH:mm 'UTC'";
        return timestamp.UtcDateTime.ToString(format, CultureInfo.InvariantCulture);
    }

    private string FormatBar(CandleSnapshot candle) =>
        $"{FormatTimestamp(candle.Timestamp)}  |  " +
        $"O {FormatPrice(candle.Open)}  H {FormatPrice(candle.High)}  " +
        $"L {FormatPrice(candle.Low)}  C {FormatPrice(candle.Close)}  |  " +
        $"V {candle.Volume.ToString("N0", CultureInfo.InvariantCulture)}";

    private static string FormatPrice(decimal value)
    {
        var format = Math.Abs(value) >= 1m ? "N2" : "N4";
        return value.ToString(format, CultureInfo.InvariantCulture);
    }
}
