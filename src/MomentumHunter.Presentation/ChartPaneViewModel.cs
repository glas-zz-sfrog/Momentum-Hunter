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
    {
        Pane = pane;
        Candles = new ObservableCollection<CandleSnapshot>(candles);
        Pane.PropertyChanged += OnPanePropertyChanged;
    }

    public PaneState Pane { get; }

    public ObservableCollection<CandleSnapshot> Candles { get; }

    public string Title => $"Chart {Pane.LinkGroup}  |  {Pane.Symbol}";

    public string ContextLabel => Pane.IsPinned
        ? "Pinned chart context"
        : $"Link {Pane.LinkGroup} chart context";

    public void ReplaceCandles(IEnumerable<CandleSnapshot> candles)
    {
        Candles.Clear();
        foreach (var candle in candles)
        {
            Candles.Add(candle);
        }
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
        }
    }
}
