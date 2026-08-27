using System.Xml.Linq;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class CommandCenterModelsTests
{
    private static readonly DateTimeOffset Now = DateTimeOffset.Parse("2026-08-26T18:00:00Z");

    [Theory]
    [InlineData(0, "NEW", "NEW 0m")]
    [InlineData(29, "NEW", "NEW 29m")]
    [InlineData(30, "RECENT", "RECENT 30m")]
    [InlineData(119, "RECENT", "RECENT 119m")]
    [InlineData(120, "EARLIER", "EARLIER 2h")]
    [InlineData(1439, "EARLIER", "EARLIER 23h 59m")]
    [InlineData(1440, "EARLIER", "SEEN 2026-08-25")]
    public void UiAgeUsesExactPresentationBoundaries(int minutesOld, string category, string label)
    {
        var view = CommandCenterAgeView.From(Now.AddMinutes(-minutesOld), Now);

        Assert.Equal(category, view.Category);
        Assert.Equal(label, view.Label);
        Assert.Contains("not discovery time", view.Detail, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("does not affect rank", view.Detail, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void FutureObservationUsesAgeUnknown()
    {
        var view = CommandCenterAgeView.From(Now.AddSeconds(1), Now);

        Assert.Equal("AGE UNKNOWN", view.Category);
        Assert.Equal("AGE UNKNOWN", view.Label);
    }

    [Fact]
    public void AttentionProjectionPreservesSourceOrderAndRankRegardlessOfUiAge()
    {
        var source = new[]
        {
            Candidate("FIRST", Now.AddHours(-5), "MISSED ENTRY", ReadinessState.ReadyForSimulation),
            Candidate("SECOND", Now.AddMinutes(-2), "RECLAIM READY", ReadinessState.StaleData),
            Candidate("THIRD", Now.AddMinutes(-45), "UNKNOWN", ReadinessState.NeedsEvidence),
        };

        var projected = CommandCenterAttentionRowView.ProjectSourceOrder(source, Now);

        Assert.Equal(["FIRST", "SECOND", "THIRD"], projected.Select(row => row.Symbol));
        Assert.Equal([1, 2, 3], projected.Select(row => row.Rank));
        Assert.Equal(["EARLIER", "NEW", "RECENT"], projected.Select(row => row.AgeCategory));
        Assert.Equal("MISSED ENTRY", projected[0].OpportunityLabel);
        Assert.Equal("READY", projected[0].EvidenceLabel);
    }

    [Theory]
    [InlineData("MISSED ENTRY", "READY")]
    [InlineData("UNKNOWN", "HISTORY LOADING")]
    [InlineData("RECLAIM READY", "QUOTE STALE")]
    public void OpportunityAndEvidenceFixturesRemainIndependent(string opportunity, string evidence)
    {
        var pair = new CommandCenterStatePairView(
            opportunity,
            evidence,
            "Exact exposed opportunity wording.",
            "Exact exposed evidence wording.");

        Assert.Equal(opportunity, pair.OpportunityLabel);
        Assert.Equal(evidence, pair.EvidenceLabel);
        Assert.NotEqual(pair.OpportunityLabel, pair.EvidenceLabel);
    }

    [Theory]
    [InlineData("MISSED ENTRY", ReadinessState.ReadyForSimulation, "READY", "READY")]
    [InlineData("UNKNOWN", ReadinessState.NeedsEvidence, "HISTORY LOADING", "HISTORY LOADING")]
    [InlineData("RECLAIM READY", ReadinessState.StaleData, "QUOTE STALE", "QUOTE STALE")]
    public void CandidateProjectionPreservesExactIndependentStatePairLabels(
        string opportunity,
        ReadinessState readiness,
        string quality,
        string expectedEvidence)
    {
        var candidate = Candidate("NVDA", Now, opportunity, readiness, quality);

        var attention = CommandCenterAttentionRowView.From(candidate, 1, Now);
        var pair = CommandCenterStatePairView.From(candidate, chart: null);

        Assert.Equal(opportunity, attention.OpportunityLabel);
        Assert.Equal(expectedEvidence, attention.EvidenceLabel);
        Assert.Equal(opportunity, pair.OpportunityLabel);
        Assert.Equal(expectedEvidence, pair.EvidenceLabel);
    }

    [Fact]
    public void GenericNeedsEvidenceDoesNotInferHistoryLoading()
    {
        var candidate = Candidate("NVDA", Now, "UNKNOWN", ReadinessState.NeedsEvidence, "Stored quality detail");

        var attention = CommandCenterAttentionRowView.From(candidate, 1, Now);
        var pair = CommandCenterStatePairView.From(candidate, chart: null);

        Assert.Equal("NEEDS EVIDENCE", attention.EvidenceLabel);
        Assert.Equal("NEEDS EVIDENCE", pair.EvidenceLabel);
        Assert.NotEqual("HISTORY LOADING", pair.EvidenceLabel);
    }

    [Fact]
    public void DecisionLabelsMissingTargetTwoAndSetupWithoutFallbackNumbers()
    {
        var decision = CommandCenterDecisionView.From(
            Candidate("NVDA", Now, "TRADEPLAN READY", ReadinessState.ReadyForSimulation),
            Plan("NVDA"),
            chart: null);

        Assert.Equal(CommandCenterDecisionView.UnavailableInCurrentReadModel, decision.Target2Label);
        Assert.Equal(CommandCenterDecisionView.UnavailableInCurrentReadModel, decision.SetupTypeLabel);
        Assert.Equal("$130.00", decision.Target1Label);
        Assert.Equal("Simulation-only", decision.Answer);
        Assert.NotEqual(decision.StatePair.OpportunityLabel, decision.StatePair.EvidenceLabel);
    }

    [Fact]
    public void TimelineCombinesTraceableSourcesInReverseChronology()
    {
        var activities = new[]
        {
            new ActivityEvent(Now.AddMinutes(-20), "Readiness", "Evidence changed.", "NVDA", HealthState.Degraded),
            new ActivityEvent(Now.AddMinutes(-5), "Other", "Other symbol event.", "MSFT", HealthState.Healthy),
        };
        var story = Story(Now.AddMinutes(-10));
        var research = Research(Now.AddMinutes(-30));

        var timeline = CommandCenterTimelineItemView.Compose(activities, story, research, "NVDA");

        Assert.Equal(3, timeline.Count);
        Assert.Equal(["CANDIDATE STORY", "ACTIVITY", "TECHNICAL RESEARCH"], timeline.Select(row => row.SourceKind));
        Assert.True(timeline[0].HasStableHistoricalIdentity);
        Assert.Equal("capture-identity-1", timeline[0].Identity);
        Assert.DoesNotContain(timeline, row => row.Symbol == "MSFT");
    }

    [Fact]
    public void TimelineSelectionDistinguishesCurrentFromHistoricalWithoutBorrowingPlanValues()
    {
        var current = CommandCenterTimelineSelectionView.From(null, "NVDA");
        var historicalItem = CommandCenterTimelineItemView.Compose([], Story(Now.AddMinutes(-10)), null, "NVDA").Single();
        var historical = CommandCenterTimelineSelectionView.From(historicalItem, "NVDA");

        Assert.Equal("CURRENT", current.ContextLabel);
        Assert.Equal("HISTORICAL EVIDENCE", historical.ContextLabel);
        Assert.Equal("capture-identity-1", historical.IdentityLabel);
        Assert.Equal("CANDIDATE STORY", historical.SourceLabel);
        Assert.Contains("current chart and TradePlan are not historical context", historical.Limitation, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void DecisionHistoricalContextAppearsOnlyForStableCandidateStoryEvidence()
    {
        var historicalItem = CommandCenterTimelineItemView.Compose([], Story(Now.AddMinutes(-10)), null, "NVDA").Single();
        var activityItem = CommandCenterTimelineItemView.Compose(
            [new ActivityEvent(Now, "Readiness", "Recorded change.", "NVDA", HealthState.Healthy)],
            null,
            null,
            "NVDA").Single();

        var historical = CommandCenterHistoricalDecisionContextView.From(historicalItem);
        var recorded = CommandCenterHistoricalDecisionContextView.From(activityItem);

        Assert.True(historical.IsVisible);
        Assert.Equal("HISTORICAL EVIDENCE", historical.ContextLabel);
        Assert.Equal("CANDIDATE STORY", historical.SourceLabel);
        Assert.Equal("capture-identity-1", historical.IdentityLabel);
        Assert.Contains("CURRENT answer", historical.Limitation, StringComparison.Ordinal);
        Assert.False(recorded.IsVisible);
    }

    [Fact]
    public async Task SelectingTimelineEvidenceDoesNotOverwriteCurrentCandidateOrTradePlan()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();
        var candidate = viewModel.SelectedCandidate;
        var plan = viewModel.TradePlan;
        var historicalItem = CommandCenterTimelineItemView.Compose([], Story(Now.AddMinutes(-10)), null, "NVDA").Single();

        var currentAnswer = viewModel.CurrentDecision.Answer;
        viewModel.SelectedTimelineItem = historicalItem;

        Assert.Same(candidate, viewModel.SelectedCandidate);
        Assert.Same(plan, viewModel.TradePlan);
        Assert.Equal(currentAnswer, viewModel.CurrentDecision.Answer);
        Assert.Equal("HISTORICAL EVIDENCE", viewModel.TimelineSelection.ContextLabel);
        Assert.True(viewModel.HistoricalDecisionContext.IsVisible);

        viewModel.ReturnToCurrentCommand.Execute(null);

        Assert.Null(viewModel.SelectedTimelineItem);
        Assert.Same(candidate, viewModel.SelectedCandidate);
        Assert.Same(plan, viewModel.TradePlan);
        Assert.Equal(currentAnswer, viewModel.CurrentDecision.Answer);
        Assert.False(viewModel.HistoricalDecisionContext.IsVisible);
    }

    [Theory]
    [InlineData("HEALTHY", "DATA HEALTHY")]
    [InlineData("PARTIAL", "DATA PARTIAL")]
    [InlineData("DEGRADED", "DATA DEGRADED")]
    [InlineData("UNAVAILABLE", "DATA UNAVAILABLE")]
    public void CompactHealthUsesDataPrefixAndExistingDiagnosticTruth(string sourceStatus, string expected)
    {
        var diagnostics = new HealthDiagnosticsView(sourceStatus, "Exact summary", "Exact check time", []);

        var compact = CommandCenterHealthView.From(diagnostics);

        Assert.Equal(expected, compact.StatusLabel);
        Assert.Equal("Exact summary", compact.Summary);
        Assert.Equal("Exact check time", compact.CheckedAtLabel);
    }

    [Fact]
    public void LiveWorkspaceUsesExistingPaneKindsWithCommandCenterTitlesAndVisibleTimeline()
    {
        var registry = WorkspaceFactory.Create(WorkspaceKind.Live);

        Assert.Equal("Live Universe", registry.Panes.Single(pane => pane.Kind == PaneKind.Hunter).Title);
        Assert.Equal("Focus Candidate / Market Story", registry.Panes.Single(pane => pane.Kind == PaneKind.Chart).Title);
        Assert.Equal("Decision / Why / Evidence", registry.Panes.Single(pane => pane.Kind == PaneKind.TradePlan).Title);
        var timeline = registry.Panes.Single(pane => pane.Kind == PaneKind.Activity);
        Assert.Equal("What Changed / Decision Timeline", timeline.Title);
        Assert.True(timeline.IsVisible);
        Assert.Single(registry.Panes.Where(pane => pane.Kind == PaneKind.Hunter));
        Assert.Single(registry.Panes.Where(pane => pane.Kind == PaneKind.Chart));
        Assert.Single(registry.Panes.Where(pane => pane.Kind == PaneKind.TradePlan));
        Assert.Single(registry.Panes.Where(pane => pane.Kind == PaneKind.Activity));
    }

    [Fact]
    public void CommandCenterXamlReusesContentIdsAndHasNoPrimarySimulationAction()
    {
        var path = Path.Combine(FindRepositoryRoot(), "src", "MomentumHunter.Desktop.Wpf", "MainWindow.xaml");
        var text = File.ReadAllText(path);
        var commandCenter = text[
            text.IndexOf("x:Name=\"HunterAnchor\"", StringComparison.Ordinal)..
            text.IndexOf("x:Name=\"CandidateStoryAnchor\"", StringComparison.Ordinal)];

        Assert.DoesNotContain("TradePlanActionButton_Click", commandCenter, StringComparison.Ordinal);
        Assert.DoesNotContain("PrimaryActionLabel", commandCenter, StringComparison.Ordinal);
        Assert.DoesNotContain("PauseOrResumeButton_Click", text, StringComparison.Ordinal);
        Assert.DoesNotContain("RunScanNowButton_Click", text, StringComparison.Ordinal);
        Assert.DoesNotContain("MonitoringToggleLabel", text, StringComparison.Ordinal);
        Assert.DoesNotContain("Run Scan Now", text, StringComparison.Ordinal);
        Assert.Contains("Informational evidence. No simulation or order controls", commandCenter, StringComparison.Ordinal);
        Assert.Contains("HistoricalDecisionContext.IsVisible", commandCenter, StringComparison.Ordinal);
        Assert.Contains("HISTORICAL EVIDENCE", commandCenter, StringComparison.Ordinal);
        Assert.Contains("ReturnToCurrentCommand", commandCenter, StringComparison.Ordinal);
        Assert.Contains("CurrentDecision.ContextLabel", commandCenter, StringComparison.Ordinal);
        Assert.Contains("DockMinWidth=\"236\"", text, StringComparison.Ordinal);
        Assert.Contains("DockMinWidth=\"312\"", text, StringComparison.Ordinal);
        foreach (var contentId in new[] { "pane-hunter", "pane-primary-chart", "pane-trade-plan", "pane-activity" })
        {
            Assert.Equal(1, Count(text, $"ContentId=\"{contentId}\""));
        }

        _ = XDocument.Load(path);
    }

    [Fact]
    public void CompactXamlProtectsCriticalTitleCandidateAndHistoryContent()
    {
        var path = Path.Combine(FindRepositoryRoot(), "src", "MomentumHunter.Desktop.Wpf", "MainWindow.xaml");
        var text = File.ReadAllText(path);
        var titleBar = text[
            text.IndexOf("x:Name=\"IntegratedTitleBar\"", StringComparison.Ordinal)..
            text.IndexOf("<avalon:DockingManager", StringComparison.Ordinal)];
        var menu = text[
            text.IndexOf("x:Name=\"ApplicationMenuPopup\"", StringComparison.Ordinal)..
            text.IndexOf("x:Name=\"CommandPaletteOverlay\"", StringComparison.Ordinal)];
        var candidateTemplate = text[
            text.IndexOf("x:Name=\"CandidateGrid\"", StringComparison.Ordinal)..
            text.IndexOf("x:Name=\"ChartDocumentPane\"", StringComparison.Ordinal)];
        var timeline = text[
            text.IndexOf("x:Name=\"ActivityAnchor\"", StringComparison.Ordinal)..
            text.IndexOf("x:Name=\"DiagnosticsAnchor\"", StringComparison.Ordinal)];

        Assert.DoesNotContain("WorkspaceButton_Click", titleBar, StringComparison.Ordinal);
        Assert.Equal(3, Count(menu, "Click=\"WorkspaceButton_Click\""));
        Assert.Contains("Tag=\"Live\"", menu, StringComparison.Ordinal);
        Assert.Contains("Tag=\"Replay\"", menu, StringComparison.Ordinal);
        Assert.Contains("Tag=\"Review\"", menu, StringComparison.Ordinal);
        foreach (var requiredTitleContent in new[]
                 {
                     "Tag=\"1m\"",
                     "Open Command Palette",
                     "READ-ONLY RESEARCH",
                     "PositionsButtonLabel",
                     "ActivityLabel",
                     "CommandCenterHealth.StatusLabel",
                     "x:Name=\"ApplicationMenuButton\"",
                     "x:Name=\"MinimizeWindowButton\"",
                     "x:Name=\"MaximizeRestoreWindowButton\"",
                     "x:Name=\"CloseWindowButton\"",
                 })
        {
            Assert.Contains(requiredTitleContent, titleBar, StringComparison.Ordinal);
        }

        Assert.Contains("MinWidth=\"118\"", titleBar, StringComparison.Ordinal);
        Assert.Contains("<Grid Grid.Row=\"2\" Grid.ColumnSpan=\"3\"", candidateTemplate, StringComparison.Ordinal);
        Assert.Contains("Text=\"{Binding AgeLabel}\"", candidateTemplate, StringComparison.Ordinal);
        Assert.True(
            candidateTemplate.IndexOf("Text=\"{Binding ChangeLabel}\"", StringComparison.Ordinal)
            < candidateTemplate.IndexOf("Text=\"{Binding AgeLabel}\"", StringComparison.Ordinal));
        Assert.Contains("HasStableHistoricalIdentity", timeline, StringComparison.Ordinal);
        Assert.Contains("AncestorType={x:Type ListBoxItem}", timeline, StringComparison.Ordinal);
        Assert.Contains("Background\" Value=\"#3A3524", timeline, StringComparison.Ordinal);
        Assert.Contains("BorderBrush\" Value=\"{StaticResource Amber}", timeline, StringComparison.Ordinal);

        var document = XDocument.Load(path);
        var priceAndChange = document
            .Descendants()
            .Single(element => string.Equals(
                (string?)element.Attribute("Text"),
                "{Binding CurrentMarketStory.PriceAndChangeLabel}",
                StringComparison.Ordinal));
        Assert.Equal("StackPanel", priceAndChange.Parent?.Name.LocalName);
        Assert.Null(priceAndChange.Parent?.Attribute("Orientation"));
        Assert.Equal(
            "{Binding CurrentMarketStory.PriceAndChangeLabel}",
            (string?)priceAndChange.Attribute("ToolTip"));
    }

    private static CandidateSnapshot Candidate(
        string symbol,
        DateTimeOffset observedAt,
        string opportunity,
        ReadinessState readiness,
        string quality = "Stored quality") => new(
        symbol,
        $"{symbol} Company",
        100m,
        2.5m,
        1_000_000,
        2.1m,
        "Stored catalyst",
        readiness,
        quality,
        observedAt,
        70,
        "Stored liquidity",
        null,
        new DataLineage("Stored source", observedAt, "Stored lineage"),
        opportunity,
        ["Persisted opportunity note"]);

    private static TradePlanSnapshot Plan(string symbol) => new(
        symbol,
        110m,
        105m,
        130m,
        5m,
        20,
        4m,
        ReadinessState.ReadyForSimulation,
        [],
        "Run FakeBroker simulation",
        new DataLineage("Stored plan", Now, "Stored plan lineage"),
        [],
        new RiskDecision(true, "Simulation-only", "Persisted risk evidence permits research simulation only.", []));

    private static CandidateStorySnapshot Story(DateTimeOffset capturedAt) => new(
        1,
        "NVDA",
        CandidateStoryEvidenceState.Available,
        Now,
        capturedAt,
        "Candidate Story source",
        "Stored candidate history.",
        "NVIDIA",
        "Technology",
        "Semiconductors",
        "WATCHED",
        "Stored status detail.",
        "First seen",
        "Latest seen",
        "Peak score",
        100m,
        105m,
        5m,
        60m,
        70m,
        72m,
        1,
        1,
        1,
        [new CandidateStoryPointSnapshot(
            1,
            "capture-identity-1",
            "capture-1",
            capturedAt,
            "Stored capture time",
            "Capture 1",
            "regular",
            "RTH",
            "Schwab",
            "Scanner",
            "READ_ONLY",
            "Calendar",
            "TRUSTED",
            101m,
            65m,
            1_000_000,
            2m,
            null,
            1m,
            null,
            "Candidate captured.",
            "Later annotation.",
            "capture source",
            "annotation source",
            [],
            true)],
        [],
        true);

    private static TechnicalResearchSnapshot Research(DateTimeOffset eventAt) => new(
        1,
        "NVDA",
        TechnicalResearchState.Available,
        Now,
        eventAt,
        "Stored technical event.",
        "Technical source",
        1,
        0,
        1,
        0,
        1,
        0,
        0,
        [],
        [new TechnicalResearchEventSnapshot(
            "technical-1",
            eventAt,
            "breakout",
            "5m",
            "PRESENT",
            "GOOD",
            "SUFFICIENT",
            100m,
            1m,
            2m,
            true,
            true,
            "Stored event detail.")],
        []);

    private static int Count(string value, string text) =>
        value.Split(text, StringSplitOptions.None).Length - 1;

    private static string FindRepositoryRoot()
    {
        for (var current = new DirectoryInfo(AppContext.BaseDirectory); current is not null; current = current.Parent)
        {
            if (File.Exists(Path.Combine(current.FullName, "AGENTS.md")))
            {
                return current.FullName;
            }
        }

        throw new DirectoryNotFoundException("Repository root was not found.");
    }
}
