using MomentumHunter.Application;
using MomentumHunter.EngineBridge;
using MomentumHunter.Infrastructure;
using MomentumHunter.Presentation;

namespace MomentumHunter.Integration.Tests;

public sealed class BackgroundCollectionLifecycleTests
{
    [Fact]
    public async Task NormalCloseSavesThenHidesWhileCollectionRemainsAvailable()
    {
        await using var harness = new LifecycleHarness();
        await harness.InitializeAsync();

        var action = await harness.Coordinator.RequestWindowCloseAsync(harness.Workstation);
        var scan = await harness.Coordinator.RunScanNowAsync();

        Assert.Equal(WorkstationCloseAction.HideToTray, action);
        Assert.Equal(["save", "hide"], harness.Workstation.Events);
        Assert.True(scan.Completed);
        Assert.Equal(BackgroundCollectionState.Healthy, harness.Background.Status.State);
        Assert.Equal(1, harness.Tray.InitializeCount);
        Assert.Equal(1, harness.Notifications.FirstCloseNoticeCount);
    }

    [Fact]
    public async Task FirstCloseNoticeOnlyAppearsOnceAndCanPersistDismissal()
    {
        await using var harness = new LifecycleHarness();
        await harness.InitializeAsync();

        await harness.Coordinator.RequestWindowCloseAsync(harness.Workstation);
        await harness.Coordinator.RequestWindowCloseAsync(harness.Workstation);
        await harness.Notifications.DismissFirstCloseNoticeAsync(doNotShowAgain: true);

        Assert.Equal(1, harness.Notifications.FirstCloseNoticeCount);
        Assert.True(harness.Coordinator.Settings.FirstCloseNoticeDismissed);
        Assert.Contains(harness.SettingsStore.SavedSettings, settings => settings.FirstCloseNoticeDismissed);
    }

    [Fact]
    public async Task ExplicitExitStopsCollectionFlushesSettingsAndDisposesTray()
    {
        await using var harness = new LifecycleHarness();
        await harness.InitializeAsync();

        await harness.Coordinator.RequestExplicitExitAsync(harness.Workstation);
        await harness.Coordinator.RequestExplicitExitAsync(harness.Workstation);

        Assert.True(harness.Coordinator.IsExplicitShutdown);
        Assert.Equal(BackgroundCollectionState.Stopping, harness.Background.Status.State);
        Assert.Equal(1, harness.Tray.DisposeCount);
        Assert.Single(harness.SettingsStore.SavedSettings);
        Assert.Equal(["save"], harness.Workstation.Events);
    }

    [Fact]
    public async Task SessionEndingBypassesCloseToTrayAndUsesExplicitShutdown()
    {
        await using var harness = new LifecycleHarness();
        await harness.InitializeAsync();

        var action = await harness.Coordinator.RequestWindowCloseAsync(harness.Workstation, isSessionEnding: true);

        Assert.Equal(WorkstationCloseAction.Shutdown, action);
        Assert.Equal(["save"], harness.Workstation.Events);
        Assert.Equal(BackgroundCollectionState.Stopping, harness.Background.Status.State);
        Assert.Equal(1, harness.Tray.DisposeCount);
    }

    [Fact]
    public async Task PausePreventsCyclesAndResumeAllowsOneNewCycle()
    {
        await using var harness = new LifecycleHarness();
        await harness.InitializeAsync();

        var first = await harness.Coordinator.RunScanNowAsync();
        await harness.Coordinator.PauseOrResumeAsync();
        var paused = await harness.Coordinator.RunScanNowAsync();
        await harness.Coordinator.PauseOrResumeAsync();
        var resumed = await harness.Coordinator.RunScanNowAsync();

        Assert.True(first.Completed);
        Assert.False(paused.Completed);
        Assert.Contains("paused", paused.Summary, StringComparison.OrdinalIgnoreCase);
        Assert.True(resumed.Completed);
        Assert.Equal(2, harness.Background.Status.CycleCount);
        Assert.Contains(harness.Tray.Statuses, status => status.State == BackgroundCollectionState.Paused);
        Assert.Equal(BackgroundCollectionState.Healthy, harness.Background.Status.State);
    }

    [Fact]
    public async Task RunScanNowDoesNotOverlapAnActiveCycle()
    {
        var cycleStarted = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var releaseCycle = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        await using var background = new DeterministicBackgroundCollectionService(
            interval: TimeSpan.FromDays(1),
            runCycle: async cancellationToken =>
            {
                cycleStarted.TrySetResult(true);
                await releaseCycle.Task.WaitAsync(cancellationToken);
            });
        await background.StartAsync();

        var firstCycle = background.RunScanNowAsync();
        await cycleStarted.Task.WaitAsync(TimeSpan.FromSeconds(3));
        var overlappingCycle = await background.RunScanNowAsync();
        releaseCycle.TrySetResult(true);
        var completedCycle = await firstCycle;

        Assert.False(overlappingCycle.Completed);
        Assert.Contains("already running", overlappingCycle.Summary, StringComparison.OrdinalIgnoreCase);
        Assert.True(completedCycle.Completed);
        Assert.Equal(1, background.Status.CycleCount);
    }

    [Fact]
    public async Task TrayReceivesHealthAndBlockedStateChanges()
    {
        await using var harness = new LifecycleHarness(runCycle: _ => throw new InvalidOperationException("test collection failure"));
        await harness.InitializeAsync();

        var result = await harness.Coordinator.RunScanNowAsync();

        Assert.False(result.Completed);
        Assert.Equal(BackgroundCollectionState.Blocked, harness.Background.Status.State);
        Assert.Contains(harness.Tray.Statuses, status => status.State == BackgroundCollectionState.Healthy);
        Assert.Contains(harness.Tray.Statuses, status => status.State == BackgroundCollectionState.Blocked);
        Assert.Contains(harness.Tray.Notifications, notification => notification.Message.Contains("Action required", StringComparison.Ordinal));
    }

    [Fact]
    public async Task BlockedMonitoringDoesNotPauseAndCanRecoverThroughAnExplicitRetry()
    {
        var attempt = 0;
        await using var harness = new LifecycleHarness(runCycle: _ =>
        {
            attempt++;
            return attempt == 1
                ? Task.FromException(new InvalidOperationException("transient test failure"))
                : Task.CompletedTask;
        });
        await harness.InitializeAsync();

        await harness.Coordinator.RunScanNowAsync();
        await harness.Coordinator.PauseOrResumeAsync();
        var recovered = await harness.Coordinator.RunScanNowAsync();

        Assert.True(recovered.Completed);
        Assert.Equal(BackgroundCollectionState.Healthy, harness.Background.Status.State);
        Assert.Contains(harness.Tray.Notifications, notification => notification.Message.Contains("recovered", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public async Task ReopenAndSystemStatusUseTheExistingWorkstationPresentation()
    {
        await using var harness = new LifecycleHarness();
        await harness.InitializeAsync();

        harness.Coordinator.RestoreWorkstation(harness.Workstation);
        harness.Coordinator.OpenSystemStatus(harness.Workstation);

        Assert.Equal(["restore", "restore", "system-status"], harness.Workstation.Events);
    }

    [Fact]
    public async Task CoordinatorInitializationIsIdempotentAndDoesNotCreateASecondTray()
    {
        await using var harness = new LifecycleHarness();

        await harness.InitializeAsync();
        await harness.Coordinator.InitializeAsync();

        Assert.Equal(1, harness.Tray.InitializeCount);
        Assert.Single(harness.Tray.Statuses.Where(status => status.State == BackgroundCollectionState.Starting));
    }

    [Fact]
    public async Task SecondLaunchSignalsTheExistingInstanceInsteadOfBecomingPrimary()
    {
        var identity = $"MomentumHunter.R005.Tests.{Guid.NewGuid():N}";
        using var first = new SingleInstanceCoordinator(identity);
        using var second = new SingleInstanceCoordinator(identity);
        var activation = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        first.ActivationRequested += (_, _) => activation.TrySetResult(true);

        Assert.True(first.TryAcquirePrimary());
        Assert.False(second.TryAcquirePrimary());

        second.SignalPrimary();
        await activation.Task.WaitAsync(TimeSpan.FromSeconds(3));
    }

    [Fact]
    public async Task DisposedPrimaryReleasesItsInstanceIdentityForTheNextLaunch()
    {
        var identity = $"MomentumHunter.R005.Tests.{Guid.NewGuid():N}";
        var first = new SingleInstanceCoordinator(identity);
        Assert.True(first.TryAcquirePrimary());
        await Task.Yield();
        first.Dispose();

        using var replacement = new SingleInstanceCoordinator(identity);
        Assert.True(replacement.TryAcquirePrimary());
    }

    [Fact]
    public async Task TraySettingsRoundTripAndCorruptSettingsFallBackToSafeDefaults()
    {
        var directory = Path.Combine(Path.GetTempPath(), "MomentumHunter.R005.Tests", Guid.NewGuid().ToString("N"));
        var path = Path.Combine(directory, "background-collection-settings.json");
        try
        {
            var store = new JsonTraySettingsStore(path);
            var expected = new TraySettings(CloseToTrayEnabled: false, FirstCloseNoticeDismissed: true, NotificationsEnabled: false);

            await store.SaveAsync(expected);
            var restored = await store.LoadAsync();
            await File.WriteAllTextAsync(path, "{not valid json}");
            var fallback = await store.LoadAsync();

            Assert.Equal(expected, restored);
            Assert.Equal(new TraySettings(), fallback);
        }
        finally
        {
            if (Directory.Exists(directory))
            {
                Directory.Delete(directory, recursive: true);
            }
        }
    }

    [Fact]
    public void TraySettingsCannotRepresentExecutionAuthorization()
    {
        var settingsPropertyNames = typeof(TraySettings).GetProperties().Select(property => property.Name).ToArray();

        Assert.Equal(["CloseToTrayEnabled", "FirstCloseNoticeDismissed", "NotificationsEnabled"], settingsPropertyNames);
        Assert.DoesNotContain(settingsPropertyNames, name => name.Contains("paper", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(settingsPropertyNames, name => name.Contains("live", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(settingsPropertyNames, name => name.Contains("broker", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(settingsPropertyNames, name => name.Contains("risk", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void TrayMenuContainsOnlyLifecycleAndMonitoringCommands()
    {
        Assert.Equal(
        [
            "Open Workstation",
            "Pause Monitoring",
            "Resume Monitoring",
            "Run Scan Now",
            "View System Status",
            "Exit Momentum Hunter",
        ],
        TrayMenuDefinition.OperatorCommands);
        Assert.DoesNotContain(TrayMenuDefinition.OperatorCommands, command => command.Contains("paper", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(TrayMenuDefinition.OperatorCommands, command => command.Contains("live", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(TrayMenuDefinition.OperatorCommands, command => command.Contains("broker", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(TrayMenuDefinition.OperatorCommands, command => command.Contains("risk", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void TrayTooltipIsCompactAndDescribesTheCurrentHealth()
    {
        var status = new BackgroundCollectionStatus(
            BackgroundCollectionState.Healthy,
            DateTimeOffset.Parse("2026-07-15T12:34:56Z"),
            5,
            3,
            "Monitoring normally.");

        var tooltip = BackgroundStatusText.TrayTooltip(status);

        Assert.DoesNotContain(Environment.NewLine, tooltip, StringComparison.Ordinal);
        Assert.True(tooltip.Length <= 63);
        Assert.Contains("Momentum Hunter", tooltip, StringComparison.Ordinal);
        Assert.Contains("Healthy", tooltip, StringComparison.Ordinal);
        Assert.Contains("5 symbols", tooltip, StringComparison.Ordinal);
    }

    [Fact]
    public void ShellViewModelPresentsTheCurrentMonitoringStateWithoutChangingTheEngineContract()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        var paused = new BackgroundCollectionStatus(
            BackgroundCollectionState.Paused,
            null,
            5,
            2,
            "Monitoring paused.");

        viewModel.UpdateBackgroundStatus(paused);

        Assert.Equal("Monitoring: Paused", viewModel.BackgroundStatusLabel);
        Assert.Contains("paused", viewModel.BackgroundStatusDetail, StringComparison.OrdinalIgnoreCase);
        Assert.True(viewModel.IsMonitoringPaused);
        Assert.Equal("Resume Monitoring", viewModel.MonitoringToggleLabel);
    }

    private sealed class LifecycleHarness : IAsyncDisposable
    {
        public LifecycleHarness(Func<CancellationToken, Task>? runCycle = null)
        {
            Background = new DeterministicBackgroundCollectionService(
                interval: TimeSpan.FromDays(1),
                runCycle: runCycle);
            SettingsStore = new RecordingSettingsStore();
            Tray = new RecordingTrayService();
            Notifications = new RecordingNotificationService();
            Workstation = new RecordingWorkstation();
            Coordinator = new ApplicationLifetimeCoordinator(Background, SettingsStore, Tray, Notifications);
        }

        public DeterministicBackgroundCollectionService Background { get; }

        public RecordingSettingsStore SettingsStore { get; }

        public RecordingTrayService Tray { get; }

        public RecordingNotificationService Notifications { get; }

        public RecordingWorkstation Workstation { get; }

        public ApplicationLifetimeCoordinator Coordinator { get; }

        public Task InitializeAsync() => Coordinator.InitializeAsync();

        public async ValueTask DisposeAsync()
        {
            Coordinator.Dispose();
            await Background.DisposeAsync();
        }
    }

    private sealed class RecordingSettingsStore : ITraySettingsStore
    {
        public List<TraySettings> SavedSettings { get; } = [];

        public Task<TraySettings> LoadAsync(CancellationToken cancellationToken = default) => Task.FromResult(new TraySettings());

        public Task SaveAsync(TraySettings settings, CancellationToken cancellationToken = default)
        {
            SavedSettings.Add(settings);
            return Task.CompletedTask;
        }
    }

    private sealed class RecordingTrayService : ITrayService
    {
        public event EventHandler? OpenRequested;

        public event EventHandler? PauseOrResumeRequested;

        public event EventHandler? RunScanNowRequested;

        public event EventHandler? SystemStatusRequested;

        public event EventHandler? ExitRequested;

        public int InitializeCount { get; private set; }

        public int DisposeCount { get; private set; }

        public List<BackgroundCollectionStatus> Statuses { get; } = [];

        public List<(string Title, string Message)> Notifications { get; } = [];

        public void Initialize() => InitializeCount++;

        public void RaiseOpenRequested() => OpenRequested?.Invoke(this, EventArgs.Empty);

        public void RaisePauseOrResumeRequested() => PauseOrResumeRequested?.Invoke(this, EventArgs.Empty);

        public void RaiseRunScanNowRequested() => RunScanNowRequested?.Invoke(this, EventArgs.Empty);

        public void RaiseSystemStatusRequested() => SystemStatusRequested?.Invoke(this, EventArgs.Empty);

        public void RaiseExitRequested() => ExitRequested?.Invoke(this, EventArgs.Empty);

        public void UpdateStatus(BackgroundCollectionStatus status) => Statuses.Add(status);

        public void ShowNotification(string title, string message) => Notifications.Add((title, message));

        public void Dispose() => DisposeCount++;
    }

    private sealed class RecordingNotificationService : INotificationService
    {
        private Func<bool, Task>? _dismissed;

        public int FirstCloseNoticeCount { get; private set; }

        public Task ShowFirstCloseNoticeAsync(Func<bool, Task> dismissed, CancellationToken cancellationToken = default)
        {
            FirstCloseNoticeCount++;
            _dismissed = dismissed;
            return Task.CompletedTask;
        }

        public Task DismissFirstCloseNoticeAsync(bool doNotShowAgain) => _dismissed?.Invoke(doNotShowAgain) ?? Task.CompletedTask;
    }

    private sealed class RecordingWorkstation : IWorkstationPresentation
    {
        public List<string> Events { get; } = [];

        public Task SavePresentationStateAsync(CancellationToken cancellationToken = default)
        {
            Events.Add("save");
            return Task.CompletedTask;
        }

        public void HideWorkstation() => Events.Add("hide");

        public void RestoreWorkstation() => Events.Add("restore");

        public void OpenSystemStatus() => Events.Add("system-status");
    }
}
