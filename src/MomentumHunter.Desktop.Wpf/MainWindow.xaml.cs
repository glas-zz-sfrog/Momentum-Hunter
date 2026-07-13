using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;
using AvalonDock.Layout;
using MomentumHunter.Contracts;
using MomentumHunter.Desktop.Wpf.Controls;
using MomentumHunter.Presentation;

namespace MomentumHunter.Desktop.Wpf;

public partial class MainWindow : Window
{
    private readonly ShellViewModel _viewModel;

    public MainWindow(ShellViewModel viewModel)
    {
        _viewModel = viewModel;
        DataContext = viewModel;
        InitializeComponent();
        Closing += OnClosing;
    }

    public async Task InitializeAsync()
    {
        await _viewModel.InitializeAsync();
        RestoreWindowBounds(_viewModel.RestoredWindowBounds);
        ActivityAnchor.IsVisible = _viewModel.IsActivityOpen;
        DiagnosticsAnchor.IsVisible = false;
    }

    private async void WorkspaceButton_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string tag } && Enum.TryParse<WorkspaceKind>(tag, out var workspace))
        {
            await _viewModel.ChangeWorkspaceAsync(workspace);
            ActivityAnchor.IsVisible = _viewModel.IsActivityOpen;
            DiagnosticsAnchor.IsVisible = false;
        }
    }

    private async void IntervalButton_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string interval } && interval != _viewModel.SelectedInterval)
        {
            await _viewModel.ChangeIntervalAsync(interval);
        }
    }

    private async void CandidateGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (e.AddedItems.OfType<CandidateSnapshot>().FirstOrDefault() is { } candidate && candidate != _viewModel.SelectedCandidate)
        {
            await _viewModel.SelectCandidateAsync(candidate);
        }
    }

    private void Window_KeyDown(object sender, KeyEventArgs e)
    {
        if (Keyboard.Modifiers == ModifierKeys.Control && e.Key == Key.K)
        {
            _viewModel.ToggleCommandPaletteCommand.Execute(null);
            e.Handled = true;
        }
    }

    private void ActivityButton_Click(object sender, RoutedEventArgs e)
    {
        _viewModel.ToggleActivityCommand.Execute(null);
        ActivityAnchor.IsVisible = _viewModel.IsActivityOpen;
        ActivityAnchor.IsActive = _viewModel.IsActivityOpen;
    }

    private void DiagnosticsButton_Click(object sender, RoutedEventArgs e)
    {
        _viewModel.ToggleDiagnosticsCommand.Execute(null);
        DiagnosticsAnchor.IsVisible = _viewModel.IsDiagnosticsOpen;
        DiagnosticsAnchor.IsActive = _viewModel.IsDiagnosticsOpen;
    }

    private void NewChartButton_Click(object sender, RoutedEventArgs e)
    {
        var pane = _viewModel.AddLinkedChart();
        var chart = new CandleChart { Margin = new Thickness(12) };
        chart.SetBinding(CandleChart.CandlesProperty, new Binding(nameof(ShellViewModel.Candles)));
        var symbol = new TextBlock
        {
            Text = $"Chart {pane.LinkGroup}  |  {pane.Symbol}",
            FontFamily = new FontFamily("Segoe UI"),
            Foreground = new SolidColorBrush(Color.FromRgb(231, 237, 242)),
            FontSize = 17,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(12, 12, 12, 0),
        };
        var note = new TextBlock
        {
            Text = $"Independent pane instance | {pane.LinkGroup} does not follow Link A selections",
            FontFamily = new FontFamily("Segoe UI"),
            Foreground = new SolidColorBrush(Color.FromRgb(153, 169, 183)),
            FontSize = 11,
            Margin = new Thickness(12, 2, 12, 0),
        };
        var content = new Grid { Background = new SolidColorBrush(Color.FromRgb(23, 33, 43)) };
        content.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        content.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        content.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        Grid.SetRow(symbol, 0);
        Grid.SetRow(note, 1);
        Grid.SetRow(chart, 2);
        content.Children.Add(symbol);
        content.Children.Add(note);
        content.Children.Add(chart);

        var document = new LayoutDocument
        {
            Title = $"Chart {pane.LinkGroup}",
            ContentId = pane.InstanceId.ToString("N"),
            Content = content,
            IsActive = true,
            CanClose = true,
            CanFloat = true,
        };
        ChartDocumentPane.Children.Add(document);
    }

    private async void TradePlanActionButton_Click(object sender, RoutedEventArgs e)
    {
        await _viewModel.RunPrimaryActionAsync();
    }

    private async void SaveLayoutButton_Click(object sender, RoutedEventArgs e)
    {
        CaptureShellState();
        await _viewModel.SaveNamedLayoutAsync("Operator Layout");
    }

    private async void RestoreLayoutButton_Click(object sender, RoutedEventArgs e)
    {
        await _viewModel.RestoreNamedLayoutAsync("Operator Layout");
        RestoreWindowBounds(_viewModel.RestoredWindowBounds);
        ActivityAnchor.IsVisible = _viewModel.IsActivityOpen;
    }

    private void OnClosing(object? sender, CancelEventArgs e)
    {
        CaptureShellState();
        _viewModel.FlushLayoutAsync().GetAwaiter().GetResult();
    }

    private void CaptureShellState()
    {
        var bounds = new RectGeometry(Left, Top, ActualWidth, ActualHeight);
        var layoutSummary = string.Join(
            ";",
            DockManager.Layout.Descendents()
                .OfType<LayoutContent>()
                .Select(content => $"{content.ContentId ?? content.Title}:{content.IsActive}"));
        _viewModel.CaptureWindowState(bounds, layoutSummary, ActivityAnchor.IsVisible);
    }

    private void RestoreWindowBounds(RectGeometry? savedBounds)
    {
        if (savedBounds is null)
        {
            return;
        }

        var workArea = SystemParameters.WorkArea;
        var width = Math.Clamp(savedBounds.Width, MinWidth, workArea.Width);
        var height = Math.Clamp(savedBounds.Height, MinHeight, workArea.Height);
        Width = width;
        Height = height;
        Left = Math.Clamp(savedBounds.X, workArea.Left, workArea.Right - width);
        Top = Math.Clamp(savedBounds.Y, workArea.Top, workArea.Bottom - height);
    }
}
