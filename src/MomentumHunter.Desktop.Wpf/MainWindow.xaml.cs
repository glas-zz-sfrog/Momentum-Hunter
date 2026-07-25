using System.ComponentModel;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using AvalonDock.Layout;
using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.Desktop.Wpf.Controls;
using MomentumHunter.Presentation;

namespace MomentumHunter.Desktop.Wpf;

public partial class MainWindow : Window, IWorkstationPresentation
{
    private const string HunterContentId = "pane-hunter";
    private const string PrimaryChartContentId = "pane-primary-chart";
    private const string TradePlanContentId = "pane-trade-plan";
    private const string ActivityContentId = "pane-activity";
    private const string DiagnosticsContentId = "pane-diagnostics";
    private const string ResearchContentId = "pane-research";
    private const string WatchlistContentId = "pane-watchlist";
    private const string DailyWorkflowContentId = "pane-daily-workflow";
    private const string CandidateStoryContentId = "pane-candidate-story";
    private const string ResearchMaturityContentId = "pane-research-maturity";
    private const string AutomationContentId = "pane-automation";
    private const string OrdersContentId = "pane-orders";
    private const string PositionsContentId = "pane-positions";
    private const string ReplayEventsContentId = "pane-replay-events";
    private const string ReviewOutcomesContentId = "pane-review-outcomes";
    private const string ShadowReviewContentId = "pane-shadow-review";

    private readonly ShellViewModel _viewModel;
    private readonly IApplicationLifetimeCoordinator _lifetime;
    private readonly Dictionary<string, object> _contentById = new(StringComparer.Ordinal);
    private readonly DispatcherTimer _layoutCaptureTimer;
    private string? _builtInDockLayoutXml;
    private bool _isRestoringDockLayout;
    private bool _isInitialized;
    private bool _allowApplicationShutdown;

    public MainWindow(ShellViewModel viewModel, IApplicationLifetimeCoordinator lifetime)
    {
        _viewModel = viewModel;
        _lifetime = lifetime;
        DataContext = viewModel;
        InitializeComponent();
        _layoutCaptureTimer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromMilliseconds(30),
        };
        _layoutCaptureTimer.Tick += (_, _) =>
        {
            _layoutCaptureTimer.Stop();
            CaptureShellState();
        };
        Closing += OnClosing;
        DockManager.LayoutUpdated += (_, _) => ScheduleShellStateCapture();
        DockManager.AnchorableClosing += (_, eventArgs) => HandlePaneClosing(eventArgs.Anchorable, eventArgs);
        DockManager.DocumentClosing += (_, eventArgs) => HandlePaneClosing(eventArgs.Document, eventArgs);
        LocationChanged += (_, _) => ScheduleShellStateCapture();
        SizeChanged += (_, _) => ScheduleShellStateCapture();
        UpdateWindowChromeState();
    }

    public async Task InitializeAsync()
    {
        await _viewModel.InitializeAsync();
        InitializeContentIndex();
        _builtInDockLayoutXml = DockLayoutPersistence.Serialize(DockManager);
        EnsureAdditionalChartDocuments();
        RestoreWindowBounds(_viewModel.RestoredWindowBounds);
        RestoreWindowState(_viewModel.RestoredWindowState);
        RestoreDockLayout();
        EnsureAdditionalChartDocuments();
        ApplyRegistryVisibility();
        _isInitialized = true;
        CaptureShellState();
    }

    private async void WorkspaceButton_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string tag } && Enum.TryParse<WorkspaceKind>(tag, out var workspace))
        {
            await _viewModel.ChangeWorkspaceAsync(workspace);
            PruneDetachedChartContent();
            if (HasCompleteStaticDockLayout())
            {
                EnsureAdditionalChartDocuments();
                RestoreDockLayout();
            }
            else
            {
                RestoreDockLayout();
                EnsureAdditionalChartDocuments();
            }

            ApplyRegistryVisibility();
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

    private async void ShadowTradesGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_viewModel.Workspace == WorkspaceKind.Review
            && e.AddedItems.OfType<ShadowTradeReviewSnapshot>().FirstOrDefault() is { } trade)
        {
            await _viewModel.SelectShadowTradeAsync(trade);
        }
    }

    private async void CandidateScoreButton_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: CandidateSnapshot candidate })
        {
            CandidateGrid.SelectedItem = candidate;
            if (candidate != _viewModel.SelectedCandidate)
            {
                await _viewModel.SelectCandidateAsync(candidate);
            }

            _viewModel.TradePlanTabIndex = 1;
        }

        e.Handled = true;
    }

    private void Window_KeyDown(object sender, System.Windows.Input.KeyEventArgs e)
    {
        if (e.Key == Key.System && e.SystemKey == Key.Space)
        {
            var menuPosition = PointToScreen(new Point(0, 48));
            SystemCommands.ShowSystemMenu(this, menuPosition);
            e.Handled = true;
            return;
        }

        if (e.Key == Key.Escape && _viewModel.IsCommandPaletteOpen)
        {
            _viewModel.CloseCommandPalette();
            e.Handled = true;
            return;
        }

        if (Keyboard.Modifiers == ModifierKeys.Control && e.Key == Key.K)
        {
            if (_viewModel.IsCommandPaletteOpen)
            {
                _viewModel.CloseCommandPalette();
            }
            else
            {
                OpenCommandPalette();
            }

            e.Handled = true;
        }
    }

    private void OpenCommandPaletteButton_Click(object sender, RoutedEventArgs e) => OpenCommandPalette();

    private void Window_StateChanged(object? sender, EventArgs e) => UpdateWindowChromeState();

    private void MinimizeWindowButton_Click(object sender, RoutedEventArgs e) =>
        SystemCommands.MinimizeWindow(this);

    private void MaximizeRestoreWindowButton_Click(object sender, RoutedEventArgs e)
    {
        if (WindowState == WindowState.Maximized)
        {
            SystemCommands.RestoreWindow(this);
        }
        else
        {
            SystemCommands.MaximizeWindow(this);
        }
    }

    private void CloseWindowButton_Click(object sender, RoutedEventArgs e) =>
        SystemCommands.CloseWindow(this);

    private void UpdateWindowChromeState()
    {
        if (MaximizeRestoreGlyph is null || MaximizeRestoreWindowButton is null)
        {
            return;
        }

        var isMaximized = WindowState == WindowState.Maximized;
        MaximizeRestoreGlyph.Text = isMaximized ? "\uE923" : "\uE922";
        MaximizeRestoreWindowButton.ToolTip = isMaximized ? "Restore down" : "Maximize";
        AutomationProperties.SetName(
            MaximizeRestoreWindowButton,
            isMaximized ? "Restore window" : "Maximize window");
    }

    private async void CommandPaletteSearchBox_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        switch (e.Key)
        {
            case Key.Down:
                MoveCommandPaletteSelection(1);
                e.Handled = true;
                break;
            case Key.Up:
                MoveCommandPaletteSelection(-1);
                e.Handled = true;
                break;
            case Key.Enter:
                await ExecuteCommandPaletteItemAsync();
                e.Handled = true;
                break;
            case Key.Escape:
                _viewModel.CloseCommandPalette();
                e.Handled = true;
                break;
        }
    }

    private async void CommandPaletteResultsList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        await ExecuteCommandPaletteItemAsync();
        e.Handled = true;
    }

    private async void CommandPaletteResultsList_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            await ExecuteCommandPaletteItemAsync();
            e.Handled = true;
        }
    }

    private void Window_Activated(object? sender, EventArgs e)
    {
        if (_viewModel.IsCommandPaletteOpen)
        {
            FocusCommandPaletteSearch();
        }
    }

    private void CommandPaletteOverlay_IsVisibleChanged(
        object sender,
        DependencyPropertyChangedEventArgs e)
    {
        if (e.NewValue is true)
        {
            FocusCommandPaletteSearch();
        }
    }

    private void CommandPaletteOverlay_MouseLeftButtonDown(
        object sender,
        MouseButtonEventArgs e)
    {
        if (ReferenceEquals(e.OriginalSource, CommandPaletteOverlay))
        {
            _viewModel.CloseCommandPalette();
            e.Handled = true;
        }
    }

    private void FocusCommandPaletteSearch()
    {
        Dispatcher.BeginInvoke(
            DispatcherPriority.Input,
            () =>
            {
                CommandPaletteSearchBox.Focus();
                CommandPaletteSearchBox.SelectAll();
            });
    }

    private void ActivityButton_Click(object sender, RoutedEventArgs e)
    {
        _viewModel.ToggleActivityCommand.Execute(null);
        SetContentVisibility(ActivityContentId, _viewModel.IsActivityOpen);
    }

    private void DiagnosticsButton_Click(object sender, RoutedEventArgs e)
    {
        _viewModel.ToggleDiagnosticsCommand.Execute(null);
        SetContentVisibility(DiagnosticsContentId, _viewModel.IsDiagnosticsOpen);
        if (_viewModel.IsDiagnosticsOpen)
        {
            EnsureAnchorablePaneHeight(DiagnosticsContentId, 300);
        }
    }

    private async void NewChartButton_Click(object sender, RoutedEventArgs e)
    {
        var pane = await _viewModel.AddLinkedChartAsync();
        CreateAdditionalChartDocument(pane, activate: true);
    }

    private void OpenCommandPalette(string? query = null)
    {
        _viewModel.OpenCommandPalette(query);
    }

    private void MoveCommandPaletteSelection(int delta)
    {
        if (CommandPaletteResultsList.Items.Count == 0)
        {
            return;
        }

        var current = CommandPaletteResultsList.SelectedIndex;
        var next = current < 0
            ? 0
            : Math.Clamp(current + delta, 0, CommandPaletteResultsList.Items.Count - 1);
        CommandPaletteResultsList.SelectedIndex = next;
        CommandPaletteResultsList.ScrollIntoView(CommandPaletteResultsList.SelectedItem);
    }

    private async Task ExecuteCommandPaletteItemAsync(CommandPaletteItem? item = null)
    {
        var result = await _viewModel.ExecuteCommandPaletteItemAsync(item);
        if (!result.Executed)
        {
            return;
        }

        switch (result.Action)
        {
            case CommandPaletteAction.AddChart when result.AddedPane is not null:
                CreateAdditionalChartDocument(result.AddedPane, activate: true);
                break;
            case CommandPaletteAction.ToggleActivity:
                SetContentVisibility(ActivityContentId, _viewModel.IsActivityOpen);
                break;
            case CommandPaletteAction.ViewDiagnostics:
                SetContentVisibility(DiagnosticsContentId, true);
                break;
        }
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
        EnsureAdditionalChartDocuments();
        RestoreWindowBounds(_viewModel.RestoredWindowBounds);
        RestoreWindowState(_viewModel.RestoredWindowState);
        RestoreDockLayout();
        EnsureAdditionalChartDocuments();
        ApplyRegistryVisibility();
    }

    private void PanesButton_Click(object sender, RoutedEventArgs e) => PanesPopup.IsOpen = !PanesPopup.IsOpen;

    private void ApplicationMenuButton_Click(object sender, RoutedEventArgs e) => ApplicationMenuPopup.IsOpen = !ApplicationMenuPopup.IsOpen;

    private async void PauseOrResumeButton_Click(object sender, RoutedEventArgs e)
    {
        await _lifetime.PauseOrResumeAsync();
        ApplicationMenuPopup.IsOpen = false;
    }

    private async void RunScanNowButton_Click(object sender, RoutedEventArgs e)
    {
        await _lifetime.RunScanNowAsync();
        ApplicationMenuPopup.IsOpen = false;
    }

    private void ViewSystemStatusButton_Click(object sender, RoutedEventArgs e)
    {
        _lifetime.OpenSystemStatus(this);
        ApplicationMenuPopup.IsOpen = false;
    }

    private async void ExitApplicationButton_Click(object sender, RoutedEventArgs e)
    {
        ApplicationMenuPopup.IsOpen = false;
        await RequestExplicitExitFromUiAsync();
    }

    public async Task RequestExplicitExitFromUiAsync()
    {
        if (_lifetime.IsExplicitShutdown || !ExitConfirmationWindow.Confirm(this))
        {
            return;
        }

        await _lifetime.RequestExplicitExitAsync(this);
        AllowApplicationShutdown();
        System.Windows.Application.Current.Shutdown();
    }

    private void ShowPaneButton_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: Guid instanceId }
            || _viewModel.Registry.Find(instanceId) is not { } pane)
        {
            return;
        }

        var wasHidden = !pane.IsVisible;
        if (wasHidden && !_viewModel.ReopenPane(instanceId))
        {
            return;
        }

        if (wasHidden && pane.Kind == PaneKind.Chart && pane != _viewModel.PrimaryChartPane)
        {
            if (!string.IsNullOrWhiteSpace(pane.SoftClosedDockLayoutXml))
            {
                CreateAdditionalChartDocument(pane, activate: false);
                RestoreDockLayout(pane.SoftClosedDockLayoutXml);
                pane.SoftClosedDockLayoutXml = null;
            }
            else
            {
                CreateAdditionalChartDocument(pane, activate: true);
            }
        }

        SetContentVisibility(ContentIdForPane(pane), true);

        if (pane.Kind == PaneKind.ReviewOutcomes)
        {
            EnsureAnchorablePaneHeight(ReviewOutcomesContentId, 340);
        }
        else if (pane.Kind == PaneKind.Research)
        {
            EnsureAnchorablePaneHeight(ResearchContentId, 390);
        }

        EnsureEvidencePaneHeight(ContentIdForPane(pane));
        PanesPopup.IsOpen = false;
    }

    private async void OnClosing(object? sender, CancelEventArgs e)
    {
        if (_allowApplicationShutdown)
        {
            // Explicit shutdown already flushes the intact dock layout before WPF begins teardown.
            return;
        }

        e.Cancel = true;
        var action = await _lifetime.RequestWindowCloseAsync(this);
        if (action == WorkstationCloseAction.Shutdown)
        {
            AllowApplicationShutdown();
            System.Windows.Application.Current.Shutdown();
        }
    }

    public async Task SavePresentationStateAsync(CancellationToken cancellationToken = default)
    {
        _layoutCaptureTimer.Stop();
        CaptureShellState();
        await _viewModel.FlushLayoutAsync(cancellationToken);
    }

    public void HideWorkstation()
    {
        ShowInTaskbar = false;
        Hide();
    }

    public void RestoreWorkstation()
    {
        ShowInTaskbar = true;
        if (!IsVisible)
        {
            Show();
        }

        if (WindowState == WindowState.Minimized)
        {
            WindowState = WindowState.Normal;
        }

        Activate();
        Topmost = true;
        Topmost = false;
        Focus();
    }

    public void OpenSystemStatus()
    {
        if (!_viewModel.IsHealthOpen)
        {
            _viewModel.ToggleHealthCommand.Execute(null);
        }
    }

    public void UpdateBackgroundStatus(BackgroundCollectionStatus status) => _viewModel.UpdateBackgroundStatus(status);

    public void RecordBackgroundActivity(BackgroundCollectionActivity activity) => _viewModel.RecordBackgroundActivity(activity);

    public void AllowApplicationShutdown() => _allowApplicationShutdown = true;

    private void CaptureShellState()
    {
        if (!_isInitialized || _isRestoringDockLayout)
        {
            return;
        }

        var bounds = new RectGeometry(Left, Top, ActualWidth, ActualHeight);
        var dockLayoutXml = DockLayoutPersistence.Serialize(DockManager);
        var activityVisible = FindLayoutContent(ActivityContentId) is LayoutAnchorable { IsVisible: true };
        var windowState = WindowState == WindowState.Maximized
            ? WindowDisplayState.Maximized
            : WindowDisplayState.Normal;
        _viewModel.CaptureWindowState(bounds, dockLayoutXml, activityVisible, windowState);
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

    private void RestoreWindowState(WindowDisplayState savedState)
    {
        if (savedState == WindowDisplayState.Maximized)
        {
            WindowState = WindowState.Maximized;
        }
    }

    private void InitializeContentIndex()
    {
        _contentById[HunterContentId] = HunterAnchor.Content;
        _contentById[PrimaryChartContentId] = PrimaryChartDocument.Content;
        _contentById[TradePlanContentId] = TradePlanAnchor.Content;
        _contentById[ActivityContentId] = ActivityAnchor.Content;
        _contentById[DiagnosticsContentId] = DiagnosticsAnchor.Content;
        _contentById[ResearchContentId] = ResearchAnchor.Content;
        _contentById[WatchlistContentId] = WatchlistAnchor.Content;
        _contentById[DailyWorkflowContentId] = DailyWorkflowAnchor.Content;
        _contentById[CandidateStoryContentId] = CandidateStoryAnchor.Content;
        _contentById[ResearchMaturityContentId] = ResearchMaturityAnchor.Content;
        _contentById[AutomationContentId] = AutomationAnchor.Content;
        _contentById[OrdersContentId] = OrdersAnchor.Content;
        _contentById[PositionsContentId] = PositionsAnchor.Content;
        _contentById[ReplayEventsContentId] = ReplayEventsAnchor.Content;
        _contentById[ReviewOutcomesContentId] = ReviewOutcomesAnchor.Content;
        _contentById[ShadowReviewContentId] = ShadowReviewAnchor.Content;
    }

    private void RestoreDockLayout(string? explicitLayoutXml = null)
    {
        _isRestoringDockLayout = true;
        try
        {
            DockLayoutPersistence.TryRestore(
                DockManager,
                explicitLayoutXml ?? (HasCompleteStaticDockLayout() ? _viewModel.RestoredDockLayoutXml : _builtInDockLayoutXml),
                ResolveDockContent);
        }
        finally
        {
            _isRestoringDockLayout = false;
        }

        EnsureContextualAnchorables();
    }

    private object? ResolveDockContent(string contentId) =>
        _contentById.TryGetValue(contentId, out var content) ? content : null;

    private bool HasCompleteStaticDockLayout()
    {
        var xml = _viewModel.RestoredDockLayoutXml;
        return !string.IsNullOrWhiteSpace(xml) && new[]
        {
            HunterContentId,
            PrimaryChartContentId,
            TradePlanContentId,
            ActivityContentId,
            DiagnosticsContentId,
            ResearchContentId,
            WatchlistContentId,
            ReplayEventsContentId,
            ReviewOutcomesContentId,
            ShadowReviewContentId,
        }.All(contentId => xml.Contains(contentId, StringComparison.Ordinal));
    }

    private void PruneDetachedChartContent()
    {
        foreach (var contentId in _contentById.Keys
                     .Where(contentId => Guid.TryParse(contentId, out var instanceId) && _viewModel.Registry.Find(instanceId) is null)
                     .ToArray())
        {
            _contentById.Remove(contentId);
        }
    }

    private void EnsureAdditionalChartDocuments()
    {
        var primaryChart = _viewModel.PrimaryChartPane;
        foreach (var pane in _viewModel.Registry.Panes.Where(pane => pane.Kind == PaneKind.Chart && pane != primaryChart && pane.IsVisible))
        {
            CreateAdditionalChartDocument(pane, activate: false);
        }
    }

    // Preserve existing saved layouts while adding optional panes introduced by a newer shell version.
    private void EnsureContextualAnchorables()
    {
        var targetPane = FindLayoutContent(ActivityContentId)?.Parent as LayoutAnchorablePane
            ?? DockManager.Layout.Descendents().OfType<LayoutAnchorablePane>().LastOrDefault();
        if (targetPane is null)
        {
            return;
        }

        EnsureDailyWorkflowAnchorable();
        EnsureCandidateStoryAnchorable();
        EnsureResearchMaturityAnchorable();
        foreach (var (contentId, title) in new[]
        {
            (AutomationContentId, "Automation"),
            (OrdersContentId, "Orders"),
            (PositionsContentId, "Positions"),
        })
        {
            if (FindLayoutContent(contentId) is null && _contentById.TryGetValue(contentId, out var content))
            {
                targetPane.Children.Add(new LayoutAnchorable
                {
                    Title = title,
                    ContentId = contentId,
                    Content = content,
                    CanClose = true,
                    CanFloat = true,
                });
            }
        }
    }

    private void EnsureDailyWorkflowAnchorable()
    {
        if (FindLayoutContent(DailyWorkflowContentId) is not null
            || !_contentById.TryGetValue(DailyWorkflowContentId, out var content))
        {
            return;
        }

        var rootPanel = DockManager.Layout.RootPanel;
        var dailyWorkflowPane = new LayoutAnchorablePane
        {
            DockHeight = new GridLength(520),
            DockMinHeight = 260,
        };
        dailyWorkflowPane.Children.Add(new LayoutAnchorable
        {
            Title = "Daily Workflow",
            ContentId = DailyWorkflowContentId,
            Content = content,
            CanClose = true,
            CanFloat = true,
        });
        rootPanel.Children.Add(dailyWorkflowPane);
    }

    private void EnsureCandidateStoryAnchorable()
    {
        if (FindLayoutContent(CandidateStoryContentId) is not null
            || !_contentById.TryGetValue(CandidateStoryContentId, out var content))
        {
            return;
        }

        var candidateStoryPane = new LayoutAnchorablePane
        {
            DockHeight = new GridLength(520),
            DockMinHeight = 300,
        };
        candidateStoryPane.Children.Add(new LayoutAnchorable
        {
            Title = "Candidate Story",
            ContentId = CandidateStoryContentId,
            Content = content,
            CanClose = true,
            CanFloat = true,
        });
        DockManager.Layout.RootPanel.Children.Add(candidateStoryPane);
    }

    private void EnsureResearchMaturityAnchorable()
    {
        if (FindLayoutContent(ResearchMaturityContentId) is not null
            || !_contentById.TryGetValue(ResearchMaturityContentId, out var content))
        {
            return;
        }

        var pane = new LayoutAnchorablePane
        {
            DockHeight = new GridLength(560),
            DockMinHeight = 320,
        };
        pane.Children.Add(new LayoutAnchorable
        {
            Title = "Research Maturity",
            ContentId = ResearchMaturityContentId,
            Content = content,
            CanClose = true,
            CanFloat = true,
        });
        DockManager.Layout.RootPanel.Children.Add(pane);
    }

    private void CreateAdditionalChartDocument(PaneState pane, bool activate)
    {
        var contentId = pane.InstanceId.ToString("N");
        if (FindLayoutContent(contentId) is not null)
        {
            if (activate)
            {
                SetContentVisibility(contentId, true);
            }

            return;
        }

        var chartViewModel = _viewModel.SecondaryCharts.SingleOrDefault(item => item.Pane.InstanceId == pane.InstanceId)
            ?? new ChartPaneViewModel(pane, _viewModel.Candles);
        var chart = new CandleChart { Margin = new Thickness(12), DataContext = chartViewModel };
        chart.SetBinding(CandleChart.CandlesProperty, new Binding(nameof(ChartPaneViewModel.Candles)));
        chart.SetBinding(CandleChart.EmptyStateTextProperty, new Binding(nameof(ChartPaneViewModel.EmptyStateText)));
        chart.SetBinding(CandleChart.IntervalProperty, new Binding($"{nameof(ChartPaneViewModel.Pane)}.{nameof(PaneState.Interval)}"));
        chart.SetBinding(
            CandleChart.InspectedCandleProperty,
            new Binding(nameof(ChartPaneViewModel.InspectedBar)) { Mode = BindingMode.TwoWay });
        var symbol = new TextBlock
        {
            FontFamily = new FontFamily("Segoe UI"),
            Foreground = new SolidColorBrush(Color.FromRgb(231, 237, 242)),
            FontSize = 17,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(12, 12, 12, 0),
            DataContext = chartViewModel,
        };
        symbol.SetBinding(TextBlock.TextProperty, new Binding(nameof(ChartPaneViewModel.Title)));
        var note = new TextBlock
        {
            FontFamily = new FontFamily("Segoe UI"),
            Foreground = new SolidColorBrush(Color.FromRgb(153, 169, 183)),
            FontSize = 11,
            Margin = new Thickness(12, 2, 12, 0),
            DataContext = chartViewModel,
        };
        note.SetBinding(TextBlock.TextProperty, new Binding(nameof(ChartPaneViewModel.DetailLabel)));
        var inspectionLabel = new TextBlock
        {
            FontFamily = new FontFamily("Segoe UI"),
            Foreground = new SolidColorBrush(Color.FromRgb(74, 199, 182)),
            FontSize = 10,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(0, 0, 12, 0),
            DataContext = chartViewModel,
        };
        inspectionLabel.SetBinding(TextBlock.TextProperty, new Binding(nameof(ChartPaneViewModel.ActiveBarLabel)));
        DockPanel.SetDock(inspectionLabel, Dock.Left);
        var inspectionSummary = new TextBlock
        {
            FontFamily = new FontFamily("Segoe UI"),
            Foreground = new SolidColorBrush(Color.FromRgb(231, 237, 242)),
            FontSize = 11,
            TextTrimming = TextTrimming.CharacterEllipsis,
            DataContext = chartViewModel,
        };
        inspectionSummary.SetBinding(TextBlock.TextProperty, new Binding(nameof(ChartPaneViewModel.ActiveBarSummary)));
        var inspectionContent = new DockPanel { LastChildFill = true };
        inspectionContent.Children.Add(inspectionLabel);
        inspectionContent.Children.Add(inspectionSummary);
        var inspectionBar = new Border
        {
            BorderBrush = new SolidColorBrush(Color.FromRgb(53, 70, 82)),
            BorderThickness = new Thickness(0, 1, 0, 0),
            Padding = new Thickness(12, 7, 12, 7),
            Child = inspectionContent,
        };
        var content = new Grid { Background = new SolidColorBrush(Color.FromRgb(23, 33, 43)) };
        content.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        content.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        content.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        content.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        Grid.SetRow(symbol, 0);
        Grid.SetRow(note, 1);
        Grid.SetRow(chart, 2);
        Grid.SetRow(inspectionBar, 3);
        content.Children.Add(symbol);
        content.Children.Add(note);
        content.Children.Add(chart);
        content.Children.Add(inspectionBar);
        _contentById[contentId] = content;

        var document = new LayoutDocument
        {
            Title = $"Chart {pane.LinkGroup}",
            ContentId = contentId,
            Content = content,
            IsActive = activate,
            CanClose = true,
            CanFloat = true,
        };
        CurrentChartDocumentPane().Children.Add(document);
    }

    private LayoutDocumentPane CurrentChartDocumentPane() =>
        DockManager.Layout.Descendents().OfType<LayoutDocumentPane>().FirstOrDefault() ?? ChartDocumentPane;

    private void ApplyRegistryVisibility()
    {
        foreach (var contentId in new[]
        {
            HunterContentId,
            PrimaryChartContentId,
            TradePlanContentId,
            ActivityContentId,
            DiagnosticsContentId,
            ResearchContentId,
            WatchlistContentId,
            DailyWorkflowContentId,
            CandidateStoryContentId,
            ResearchMaturityContentId,
            AutomationContentId,
            OrdersContentId,
            PositionsContentId,
            ReplayEventsContentId,
            ReviewOutcomesContentId,
            ShadowReviewContentId,
        })
        {
            if (FindLayoutContent(contentId) is { } content)
            {
                SetContentVisibility(contentId, PaneForContent(content)?.IsVisible == true);
            }
        }

        foreach (var pane in _viewModel.Registry.Panes)
        {
            SetContentVisibility(ContentIdForPane(pane), pane.IsVisible);
            if (pane.IsVisible)
            {
                EnsureEvidencePaneHeight(ContentIdForPane(pane));
            }
        }
    }

    private void EnsureEvidencePaneHeight(string contentId)
    {
        if (!string.Equals(contentId, WatchlistContentId, StringComparison.Ordinal)
            || FindLayoutContent(contentId)?.Parent is not LayoutAnchorablePane pane
            || pane.DockHeight.Value >= 390)
        {
            return;
        }

        pane.DockHeight = new GridLength(390);
    }

    private void SetContentVisibility(string contentId, bool visible)
    {
        var content = FindLayoutContent(contentId);
        if (content is null)
        {
            return;
        }

        if (visible)
        {
            if (content is LayoutAnchorable anchorable)
            {
                anchorable.Show();
                anchorable.IsSelected = true;
                anchorable.IsActive = true;
            }
            else if (content is LayoutDocument document)
            {
                document.IsActive = true;
            }
            return;
        }

        if (content is LayoutAnchorable hideable)
        {
            hideable.Hide();
        }
    }

    private LayoutContent? FindLayoutContent(string contentId) =>
        DockManager.Layout.Descendents().OfType<LayoutContent>()
            .FirstOrDefault(content => string.Equals(content.ContentId, contentId, StringComparison.Ordinal));

    private void EnsureAnchorablePaneHeight(string contentId, double minimumHeight)
    {
        var current = FindLayoutContent(contentId)?.Parent;
        while (current is not null && current is not LayoutAnchorablePane)
        {
            current = (current as LayoutElement)?.Parent;
        }

        if (current is LayoutAnchorablePane pane &&
            (!pane.DockHeight.IsAbsolute || pane.DockHeight.Value < minimumHeight))
        {
            pane.DockHeight = new GridLength(minimumHeight);
        }
    }

    private string ContentIdForPane(PaneState pane)
    {
        if (pane == _viewModel.PrimaryChartPane)
        {
            return PrimaryChartContentId;
        }

        return pane.Kind switch
        {
            PaneKind.Hunter => HunterContentId,
            PaneKind.TradePlan => TradePlanContentId,
            PaneKind.Activity => ActivityContentId,
            PaneKind.Diagnostics => DiagnosticsContentId,
            PaneKind.Research => ResearchContentId,
            PaneKind.Watchlist => WatchlistContentId,
            PaneKind.DailyWorkflow => DailyWorkflowContentId,
            PaneKind.CandidateStory => CandidateStoryContentId,
            PaneKind.ResearchMaturity => ResearchMaturityContentId,
            PaneKind.Automation => AutomationContentId,
            PaneKind.Orders => OrdersContentId,
            PaneKind.Positions => PositionsContentId,
            PaneKind.ReplayEvents => ReplayEventsContentId,
            PaneKind.ReviewOutcomes => ReviewOutcomesContentId,
            PaneKind.ShadowReview => ShadowReviewContentId,
            _ => pane.InstanceId.ToString("N"),
        };
    }

    private PaneState? PaneForContent(LayoutContent content)
    {
        if (Guid.TryParse(content.ContentId, out var instanceId))
        {
            return _viewModel.Registry.Find(instanceId);
        }

        return content.ContentId switch
        {
            HunterContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Hunter),
            PrimaryChartContentId => _viewModel.PrimaryChartPane,
            TradePlanContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.TradePlan),
            ActivityContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Activity),
            DiagnosticsContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Diagnostics),
            ResearchContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Research),
            WatchlistContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Watchlist),
            DailyWorkflowContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.DailyWorkflow),
            CandidateStoryContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.CandidateStory),
            ResearchMaturityContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.ResearchMaturity),
            AutomationContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Automation),
            OrdersContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Orders),
            PositionsContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Positions),
            ReplayEventsContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.ReplayEvents),
            ReviewOutcomesContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.ReviewOutcomes),
            ShadowReviewContentId => _viewModel.Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.ShadowReview),
            _ => null,
        };
    }

    private void HandlePaneClosing(LayoutContent content, CancelEventArgs eventArgs)
    {
        if (_isRestoringDockLayout || PaneForContent(content) is not { } pane)
        {
            return;
        }

        var contentId = ContentIdForPane(pane);
        if (content is LayoutDocument)
        {
            pane.SoftClosedDockLayoutXml = DockLayoutPersistence.Serialize(DockManager);
            if (_viewModel.SoftClosePane(pane.InstanceId))
            {
                _contentById.Remove(contentId);
            }

            return;
        }

        eventArgs.Cancel = true;
        if (_viewModel.SoftClosePane(pane.InstanceId))
        {
            Dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(() => SetContentVisibility(contentId, false)));
        }
    }

    private void ScheduleShellStateCapture()
    {
        if (!_isInitialized || _isRestoringDockLayout)
        {
            return;
        }

        _layoutCaptureTimer.Stop();
        _layoutCaptureTimer.Start();
    }
}
