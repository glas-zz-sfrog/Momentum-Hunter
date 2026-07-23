using System.Collections.ObjectModel;
using System.ComponentModel;
using CommunityToolkit.Mvvm.ComponentModel;
using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

/// <summary>
/// Holds the display context for one chart instance. Each pane owns a copied
/// candle collection so a linked selection in another group cannot repaint it.
/// </summary>
public sealed class ChartPaneViewModel : ObservableObject
{
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

    public string EmptyStateText => DataState switch
    {
        ChartDataState.InsufficientData => "Insufficient stored candles",
        ChartDataState.Unavailable => "No stored candles available",
        _ => "No deterministic candles available",
    };

    public string Title => $"Chart {Pane.LinkGroup}  |  {Pane.Symbol}";

    public string ContextLabel => Pane.IsPinned
        ? "Pinned chart context"
        : $"Link {Pane.LinkGroup} chart context";

    public string DetailLabel => $"{ContextLabel} | {SourceSummary}";

    public void ReplaceCandles(IEnumerable<CandleSnapshot> candles)
    {
        Candles.Clear();
        foreach (var candle in candles)
        {
            Candles.Add(candle);
        }
    }

    public void ApplySnapshot(ChartSnapshot snapshot)
    {
        DataState = snapshot.State;
        DataLineage = snapshot.DataLineage;
        SourceSummary = snapshot.Summary;
        ReplaceCandles(snapshot.Candles);
        OnPropertyChanged(nameof(DataState));
        OnPropertyChanged(nameof(DataLineage));
        OnPropertyChanged(nameof(SourceSummary));
        OnPropertyChanged(nameof(EmptyStateText));
        OnPropertyChanged(nameof(DetailLabel));
    }

    private void OnPanePropertyChanged(object? sender, PropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.PropertyName is nameof(PaneState.Symbol) or nameof(PaneState.Interval) or nameof(PaneState.LinkGroup))
        {
            OnPropertyChanged(nameof(Title));
        }

        if (eventArgs.PropertyName is nameof(PaneState.IsPinned) or nameof(PaneState.LinkGroup))
        {
            OnPropertyChanged(nameof(ContextLabel));
            OnPropertyChanged(nameof(DetailLabel));
        }
    }
}
