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

    public ChartQualitySnapshot? Quality { get; private set; }

    public string SourceSummary { get; private set; } = "Chart evidence unavailable.";

    public string EmptyStateText => DataState switch
    {
        _ when IsHistoryLoading => "Loading Schwab candle history...",
        _ when HasHistoryLoadFailure => "Candle history load failed",
        ChartDataState.InsufficientData => "Insufficient stored candles",
        ChartDataState.Unavailable => "No stored candles available",
        _ => "No deterministic candles available",
    };

    public string Title => $"Chart {Pane.LinkGroup}  |  {Pane.Symbol}";

    public string ContextLabel => Pane.IsPinned
        ? "Pinned chart context"
        : $"Link {Pane.LinkGroup} chart context";

    public string DetailLabel =>
        $"{ContextLabel} | {ProviderStatusLabel} | {TimingStatusLabel} | {IntegrityStatusLabel} | {InProgressStatusLabel}";

    public string ProviderStatusLabel => Quality is null
        ? "Source unavailable"
        : IsHistoryLoading
            ? $"{Quality.Provider}  |  LOADING HISTORY"
            : HasHistoryLoadFailure
                ? $"{Quality.Provider}  |  HISTORY LOAD {Quality.HistoryLoadStatus.Replace('_', ' ')}"
                : $"{Quality.Provider}  |  {Quality.Status.Replace('_', ' ')}";

    public bool IsHistoryLoading => Quality?.HistoryLoadStatus is "QUEUED" or "RUNNING";

    public bool HasHistoryLoadFailure => Quality?.HistoryLoadStatus is "PARTIAL" or "FAILED";

    public string HistoryLoadDetail => Quality?.HistoryLoadDetail
        ?? "Automatic candle history load status unavailable.";

    public string TimingStatusLabel
    {
        get
        {
            if (Quality is null)
            {
                return "Provider and receipt times unavailable";
            }
            var completed = Quality.LatestCompletedBarAt is null
                ? "No completed bar"
                : $"Complete {FormatTimestamp(Quality.LatestCompletedBarAt.Value)}";
            var received = Quality.LatestReceiptAt is null
                ? "receipt unavailable"
                : $"received {FormatTimestamp(Quality.LatestReceiptAt.Value)}";
            var age = Quality.AgeSeconds is null
                ? "age unavailable"
                : $"age {FormatAge(Quality.AgeSeconds.Value)}";
            return $"{completed}  |  {received}  |  {age}";
        }
    }

    public string IntegrityStatusLabel => Quality is null
        ? "Gaps, corrections, and reconciliation unavailable"
        : $"Gaps {Quality.GapCount:N0}  |  Corrected {Quality.CorrectionCount:N0}  |  Unreconciled {Quality.UnreconciledCount:N0}";

    public bool HasIntegrityFindings => Quality is not null
        && (Quality.GapCount > 0 || Quality.CorrectionCount > 0 || Quality.UnreconciledCount > 0);

    public string InProgressStatusLabel => Quality?.LatestInProgressBarAt is DateTimeOffset timestamp
        ? $"In progress {FormatTimestamp(timestamp)}"
        : "No in-progress bar";

    public bool HasInProgressBar => Quality?.LatestInProgressBarAt is not null;

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
        Quality = snapshot.Quality;
        SourceSummary = snapshot.Summary;
        ReplaceCandles(snapshot.Candles);
        OnPropertyChanged(nameof(DataState));
        OnPropertyChanged(nameof(DataLineage));
        OnPropertyChanged(nameof(Quality));
        OnPropertyChanged(nameof(SourceSummary));
        OnPropertyChanged(nameof(EmptyStateText));
        OnPropertyChanged(nameof(DetailLabel));
        OnPropertyChanged(nameof(ProviderStatusLabel));
        OnPropertyChanged(nameof(IsHistoryLoading));
        OnPropertyChanged(nameof(HasHistoryLoadFailure));
        OnPropertyChanged(nameof(HistoryLoadDetail));
        OnPropertyChanged(nameof(TimingStatusLabel));
        OnPropertyChanged(nameof(IntegrityStatusLabel));
        OnPropertyChanged(nameof(HasIntegrityFindings));
        OnPropertyChanged(nameof(InProgressStatusLabel));
        OnPropertyChanged(nameof(HasInProgressBar));
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
        $"V {FormatVolume(candle.Volume)}  |  {FormatCandleState(candle)}";

    private static string FormatCandleState(CandleSnapshot candle)
    {
        var state = candle.State.Replace('_', ' ');
        if (candle.HasGapBefore)
        {
            state += " | GAP BEFORE";
        }
        return state;
    }

    private static string FormatAge(decimal seconds) => seconds switch
    {
        < 60m => $"{seconds:N0}s",
        < 3600m => $"{seconds / 60m:N1}m",
        _ => $"{seconds / 3600m:N1}h",
    };

    private static string FormatVolume(decimal value) =>
        value == decimal.Truncate(value)
            ? value.ToString("N0", CultureInfo.InvariantCulture)
            : value.ToString("N2", CultureInfo.InvariantCulture);

    private static string FormatPrice(decimal value)
    {
        var format = Math.Abs(value) >= 1m ? "N2" : "N4";
        return value.ToString(format, CultureInfo.InvariantCulture);
    }
}
