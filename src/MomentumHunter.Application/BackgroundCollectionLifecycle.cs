namespace MomentumHunter.Application;

public enum BackgroundCollectionState
{
    Starting,
    Healthy,
    Degraded,
    Paused,
    Blocked,
    Stopping,
}

public sealed record BackgroundCollectionStatus(
    BackgroundCollectionState State,
    DateTimeOffset? LastCompletedCycleAt,
    int MonitoredSymbolCount,
    int CycleCount,
    string Detail)
{
    public bool IsMonitoring => State is BackgroundCollectionState.Healthy or BackgroundCollectionState.Degraded;
}

public sealed record CollectionCycleResult(bool Completed, string Summary, BackgroundCollectionStatus Status);

public sealed record BackgroundCollectionActivity(DateTimeOffset Timestamp, string Message, BackgroundCollectionState State);

public sealed record TraySettings(
    bool CloseToTrayEnabled = true,
    bool FirstCloseNoticeDismissed = false,
    bool NotificationsEnabled = true);

public enum WorkstationCloseAction
{
    HideToTray,
    Shutdown,
}

public interface IBackgroundStatusProvider
{
    BackgroundCollectionStatus Status { get; }
}

public interface IBackgroundCollectionService : IBackgroundStatusProvider, IAsyncDisposable
{
    event Action<BackgroundCollectionStatus>? StatusChanged;

    event Action<BackgroundCollectionActivity>? ActivityRecorded;

    Task StartAsync(CancellationToken cancellationToken = default);

    Task PauseAsync(CancellationToken cancellationToken = default);

    Task ResumeAsync(CancellationToken cancellationToken = default);

    Task<CollectionCycleResult> RunScanNowAsync(CancellationToken cancellationToken = default);

    Task StopAsync(CancellationToken cancellationToken = default);
}

public interface ITraySettingsStore
{
    Task<TraySettings> LoadAsync(CancellationToken cancellationToken = default);

    Task SaveAsync(TraySettings settings, CancellationToken cancellationToken = default);
}

public interface IWorkstationPresentation
{
    Task SavePresentationStateAsync(CancellationToken cancellationToken = default);

    void HideWorkstation();

    void RestoreWorkstation();

    void OpenSystemStatus();
}

public interface ITrayService : IDisposable
{
    event EventHandler? OpenRequested;

    event EventHandler? PauseOrResumeRequested;

    event EventHandler? RunScanNowRequested;

    event EventHandler? SystemStatusRequested;

    event EventHandler? ExitRequested;

    void Initialize();

    void UpdateStatus(BackgroundCollectionStatus status);

    void ShowNotification(string title, string message);
}

public interface INotificationService
{
    Task ShowFirstCloseNoticeAsync(Func<bool, Task> dismissed, CancellationToken cancellationToken = default);
}

public interface IApplicationLifetimeCoordinator : IDisposable
{
    TraySettings Settings { get; }

    BackgroundCollectionStatus BackgroundStatus { get; }

    bool IsExplicitShutdown { get; }

    Task InitializeAsync(CancellationToken cancellationToken = default);

    Task<WorkstationCloseAction> RequestWindowCloseAsync(
        IWorkstationPresentation workstation,
        bool isSessionEnding = false,
        CancellationToken cancellationToken = default);

    void RestoreWorkstation(IWorkstationPresentation workstation);

    void OpenSystemStatus(IWorkstationPresentation workstation);

    Task PauseOrResumeAsync(CancellationToken cancellationToken = default);

    Task<CollectionCycleResult> RunScanNowAsync(CancellationToken cancellationToken = default);

    Task RequestExplicitExitAsync(
        IWorkstationPresentation workstation,
        bool isSessionEnding = false,
        CancellationToken cancellationToken = default);
}

public static class BackgroundStatusText
{
    public static string Label(BackgroundCollectionStatus status) => status.State switch
    {
        BackgroundCollectionState.Starting => "Monitoring: Starting",
        BackgroundCollectionState.Healthy => "Monitoring: Healthy",
        BackgroundCollectionState.Degraded => "Monitoring: Degraded",
        BackgroundCollectionState.Paused => "Monitoring: Paused",
        BackgroundCollectionState.Blocked => "Monitoring: Blocked",
        BackgroundCollectionState.Stopping => "Monitoring: Stopping",
        _ => "Monitoring: Unknown",
    };

    public static string Detail(BackgroundCollectionStatus status) => status.State switch
    {
        BackgroundCollectionState.Healthy when status.LastCompletedCycleAt is { } completed =>
            $"Monitoring {status.MonitoredSymbolCount} symbols. Last scan {completed:HH:mm:ss}; {status.CycleCount} cycles completed.",
        BackgroundCollectionState.Healthy => $"Monitoring {status.MonitoredSymbolCount} symbols.",
        BackgroundCollectionState.Paused => "Monitoring paused. Collection will not resume until requested.",
        BackgroundCollectionState.Degraded => "Monitoring with limited data. Open System Status for details.",
        BackgroundCollectionState.Blocked => "Background collection stopped. Action required.",
        BackgroundCollectionState.Stopping => "Stopping background services.",
        _ => status.Detail,
    };

    public static string TrayTooltip(BackgroundCollectionStatus status)
    {
        var lastScan = status.LastCompletedCycleAt is { } completed ? completed.ToString("HH:mm:ss") : "pending";
        return $"Momentum Hunter | {status.State} | {status.MonitoredSymbolCount} symbols | {lastScan}";
    }
}

public sealed class DeterministicBackgroundCollectionService : IBackgroundCollectionService
{
    private readonly object _sync = new();
    private readonly TimeProvider _timeProvider;
    private readonly TimeSpan _interval;
    private readonly Func<CancellationToken, Task> _runCycle;
    private CancellationTokenSource? _monitoringCancellation;
    private Task? _monitoringTask;
    private BackgroundCollectionStatus _status;
    private bool _started;
    private bool _cycleInProgress;

    public DeterministicBackgroundCollectionService(
        int monitoredSymbolCount = 5,
        TimeSpan? interval = null,
        TimeProvider? timeProvider = null,
        Func<CancellationToken, Task>? runCycle = null)
    {
        _timeProvider = timeProvider ?? TimeProvider.System;
        _interval = interval ?? TimeSpan.FromSeconds(5);
        _runCycle = runCycle ?? (_ => Task.CompletedTask);
        _status = new BackgroundCollectionStatus(
            BackgroundCollectionState.Starting,
            null,
            monitoredSymbolCount,
            0,
            "Waiting for monitoring to start.");
    }

    public event Action<BackgroundCollectionStatus>? StatusChanged;

    public event Action<BackgroundCollectionActivity>? ActivityRecorded;

    public BackgroundCollectionStatus Status
    {
        get
        {
            lock (_sync)
            {
                return _status;
            }
        }
    }

    public Task StartAsync(CancellationToken cancellationToken = default)
    {
        BackgroundCollectionStatus status;
        lock (_sync)
        {
            if (_started)
            {
                return Task.CompletedTask;
            }

            _started = true;
            _monitoringCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            status = _status = _status with
            {
                State = BackgroundCollectionState.Healthy,
                Detail = "Monitoring normally.",
            };
            _monitoringTask = Task.Run(() => RunMonitoringLoopAsync(_monitoringCancellation.Token), CancellationToken.None);
        }

        PublishStatus(status);
        PublishActivity("Background monitoring started.", status.State);
        return Task.CompletedTask;
    }

    public Task PauseAsync(CancellationToken cancellationToken = default)
    {
        BackgroundCollectionStatus? status = null;
        lock (_sync)
        {
            if (!_started || _status.State is not (BackgroundCollectionState.Healthy or BackgroundCollectionState.Degraded))
            {
                return Task.CompletedTask;
            }

            status = _status = _status with
            {
                State = BackgroundCollectionState.Paused,
                Detail = "Monitoring paused. Collection will not resume until requested.",
            };
        }

        PublishStatus(status);
        PublishActivity("Monitoring paused.", status.State);
        return Task.CompletedTask;
    }

    public Task ResumeAsync(CancellationToken cancellationToken = default)
    {
        BackgroundCollectionStatus? status = null;
        lock (_sync)
        {
            if (!_started || _status.State != BackgroundCollectionState.Paused)
            {
                return Task.CompletedTask;
            }

            status = _status = _status with
            {
                State = BackgroundCollectionState.Healthy,
                Detail = "Monitoring normally.",
            };
        }

        PublishStatus(status);
        PublishActivity("Monitoring resumed.", status.State);
        return Task.CompletedTask;
    }

    public async Task<CollectionCycleResult> RunScanNowAsync(CancellationToken cancellationToken = default)
    {
        BackgroundCollectionStatus skippedStatus;
        lock (_sync)
        {
            skippedStatus = _status;
            if (!_started)
            {
                return new CollectionCycleResult(false, "Monitoring has not started.", skippedStatus);
            }

            if (_status.State == BackgroundCollectionState.Paused)
            {
                return new CollectionCycleResult(false, "Monitoring is paused; no scan started.", skippedStatus);
            }

            if (_status.State == BackgroundCollectionState.Stopping)
            {
                return new CollectionCycleResult(false, "Background services are stopping; no scan started.", skippedStatus);
            }

            if (_cycleInProgress)
            {
                return new CollectionCycleResult(false, "A collection cycle is already running.", skippedStatus);
            }

            _cycleInProgress = true;
        }

        try
        {
            await _runCycle(cancellationToken);
            BackgroundCollectionStatus completed;
            lock (_sync)
            {
                completed = _status = _status with
                {
                    State = BackgroundCollectionState.Healthy,
                    LastCompletedCycleAt = _timeProvider.GetUtcNow(),
                    CycleCount = _status.CycleCount + 1,
                    Detail = "Monitoring normally.",
                };
            }

            PublishStatus(completed);
            PublishActivity($"Collection cycle {completed.CycleCount} completed.", completed.State);
            return new CollectionCycleResult(true, "Collection cycle completed.", completed);
        }
        catch (OperationCanceledException) when (_monitoringCancellation?.IsCancellationRequested == true)
        {
            return new CollectionCycleResult(false, "Collection cycle cancelled during shutdown.", Status);
        }
        catch (Exception exception)
        {
            BackgroundCollectionStatus blocked;
            lock (_sync)
            {
                blocked = _status = _status with
                {
                    State = BackgroundCollectionState.Blocked,
                    Detail = $"Background collection stopped: {exception.Message}",
                };
            }

            PublishStatus(blocked);
            PublishActivity("Background collection entered a blocked state.", blocked.State);
            return new CollectionCycleResult(false, blocked.Detail, blocked);
        }
        finally
        {
            lock (_sync)
            {
                _cycleInProgress = false;
            }
        }
    }

    public async Task StopAsync(CancellationToken cancellationToken = default)
    {
        CancellationTokenSource? cancellation;
        Task? monitoringTask;
        BackgroundCollectionStatus? status = null;
        lock (_sync)
        {
            if (!_started || _status.State == BackgroundCollectionState.Stopping)
            {
                return;
            }

            status = _status = _status with
            {
                State = BackgroundCollectionState.Stopping,
                Detail = "Stopping background services.",
            };
            cancellation = _monitoringCancellation;
            monitoringTask = _monitoringTask;
        }

        PublishStatus(status);
        PublishActivity("Background monitoring is stopping.", status.State);
        cancellation?.Cancel();
        if (monitoringTask is not null)
        {
            await monitoringTask.WaitAsync(cancellationToken);
        }
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync();
        _monitoringCancellation?.Dispose();
    }

    private async Task RunMonitoringLoopAsync(CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(_interval, _timeProvider);
        try
        {
            while (await timer.WaitForNextTickAsync(cancellationToken))
            {
                if (Status.State == BackgroundCollectionState.Paused)
                {
                    continue;
                }

                await RunScanNowAsync(cancellationToken);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
    }

    private void PublishStatus(BackgroundCollectionStatus status) => StatusChanged?.Invoke(status);

    private void PublishActivity(string message, BackgroundCollectionState state) =>
        ActivityRecorded?.Invoke(new BackgroundCollectionActivity(_timeProvider.GetUtcNow(), message, state));
}

public sealed class ApplicationLifetimeCoordinator : IApplicationLifetimeCoordinator
{
    private readonly IBackgroundCollectionService _backgroundCollection;
    private readonly ITraySettingsStore _settingsStore;
    private readonly ITrayService _tray;
    private readonly INotificationService _notifications;
    private bool _initialized;
    private bool _firstCloseNoticeShown;
    private BackgroundCollectionState _lastBackgroundState;

    public ApplicationLifetimeCoordinator(
        IBackgroundCollectionService backgroundCollection,
        ITraySettingsStore settingsStore,
        ITrayService tray,
        INotificationService notifications)
    {
        _backgroundCollection = backgroundCollection;
        _settingsStore = settingsStore;
        _tray = tray;
        _notifications = notifications;
        Settings = new TraySettings();
        _lastBackgroundState = backgroundCollection.Status.State;
    }

    public TraySettings Settings { get; private set; }

    public BackgroundCollectionStatus BackgroundStatus => _backgroundCollection.Status;

    public bool IsExplicitShutdown { get; private set; }

    public async Task InitializeAsync(CancellationToken cancellationToken = default)
    {
        if (_initialized)
        {
            return;
        }

        Settings = await _settingsStore.LoadAsync(cancellationToken);
        _backgroundCollection.StatusChanged += HandleStatusChanged;
        _tray.Initialize();
        _tray.UpdateStatus(_backgroundCollection.Status);
        _initialized = true;
        await _backgroundCollection.StartAsync(cancellationToken);
    }

    public async Task<WorkstationCloseAction> RequestWindowCloseAsync(
        IWorkstationPresentation workstation,
        bool isSessionEnding = false,
        CancellationToken cancellationToken = default)
    {
        if (isSessionEnding || !Settings.CloseToTrayEnabled)
        {
            await RequestExplicitExitAsync(workstation, isSessionEnding, cancellationToken);
            return WorkstationCloseAction.Shutdown;
        }

        await workstation.SavePresentationStateAsync(cancellationToken);
        workstation.HideWorkstation();
        if (!_firstCloseNoticeShown && !Settings.FirstCloseNoticeDismissed && Settings.NotificationsEnabled)
        {
            _firstCloseNoticeShown = true;
            await _notifications.ShowFirstCloseNoticeAsync(DismissFirstCloseNoticeAsync, cancellationToken);
        }

        return WorkstationCloseAction.HideToTray;
    }

    public void RestoreWorkstation(IWorkstationPresentation workstation) => workstation.RestoreWorkstation();

    public void OpenSystemStatus(IWorkstationPresentation workstation)
    {
        workstation.RestoreWorkstation();
        workstation.OpenSystemStatus();
    }

    public async Task PauseOrResumeAsync(CancellationToken cancellationToken = default)
    {
        if (_backgroundCollection.Status.State == BackgroundCollectionState.Paused)
        {
            await _backgroundCollection.ResumeAsync(cancellationToken);
        }
        else
        {
            await _backgroundCollection.PauseAsync(cancellationToken);
        }
    }

    public Task<CollectionCycleResult> RunScanNowAsync(CancellationToken cancellationToken = default) =>
        _backgroundCollection.RunScanNowAsync(cancellationToken);

    public async Task RequestExplicitExitAsync(
        IWorkstationPresentation workstation,
        bool isSessionEnding = false,
        CancellationToken cancellationToken = default)
    {
        if (IsExplicitShutdown)
        {
            return;
        }

        IsExplicitShutdown = true;
        await workstation.SavePresentationStateAsync(cancellationToken);
        await _settingsStore.SaveAsync(Settings, cancellationToken);
        await _backgroundCollection.StopAsync(cancellationToken);
        _tray.Dispose();
    }

    public void Dispose()
    {
        _backgroundCollection.StatusChanged -= HandleStatusChanged;
    }

    private async Task DismissFirstCloseNoticeAsync(bool doNotShowAgain)
    {
        if (!doNotShowAgain)
        {
            return;
        }

        Settings = Settings with { FirstCloseNoticeDismissed = true };
        await _settingsStore.SaveAsync(Settings);
    }

    private void HandleStatusChanged(BackgroundCollectionStatus status)
    {
        _tray.UpdateStatus(status);
        if (status.State == BackgroundCollectionState.Blocked && _lastBackgroundState != BackgroundCollectionState.Blocked)
        {
            _tray.ShowNotification("Momentum Hunter", "Background collection stopped. Action required.");
        }
        else if (_lastBackgroundState == BackgroundCollectionState.Blocked && status.State == BackgroundCollectionState.Healthy)
        {
            _tray.ShowNotification("Momentum Hunter", "Background collection recovered and is monitoring normally.");
        }

        _lastBackgroundState = status.State;
    }
}

public interface ISingleInstanceCoordinator : IDisposable
{
    event EventHandler? ActivationRequested;

    bool TryAcquirePrimary();

    void SignalPrimary();
}

public sealed class SingleInstanceCoordinator : ISingleInstanceCoordinator
{
    private readonly string _mutexName;
    private readonly string _activationEventName;
    private Mutex? _mutex;
    private EventWaitHandle? _activationEvent;
    private bool _ownsMutex;
    private int _mutexOwnerThreadId;
    private bool _disposed;

    public SingleInstanceCoordinator(string applicationIdentity = "MomentumHunter.Workstation")
    {
        _mutexName = $"Local\\{applicationIdentity}.Instance";
        _activationEventName = $"Local\\{applicationIdentity}.Activate";
    }

    public event EventHandler? ActivationRequested;

    public bool TryAcquirePrimary()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        _mutex = new Mutex(initiallyOwned: true, _mutexName, out var createdNew);
        _activationEvent = new EventWaitHandle(false, EventResetMode.AutoReset, _activationEventName);
        if (!createdNew)
        {
            _mutex.Dispose();
            _mutex = null;
            return false;
        }

        _ownsMutex = true;
        _mutexOwnerThreadId = Environment.CurrentManagedThreadId;
        _ = Task.Factory.StartNew(
            ListenForActivation,
            CancellationToken.None,
            TaskCreationOptions.LongRunning,
            TaskScheduler.Default);
        return true;
    }

    public void SignalPrimary()
    {
        using var signal = new EventWaitHandle(false, EventResetMode.AutoReset, _activationEventName);
        signal.Set();
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _activationEvent?.Dispose();
        if (_ownsMutex && _mutexOwnerThreadId == Environment.CurrentManagedThreadId)
        {
            _mutex?.ReleaseMutex();
        }

        _mutex?.Dispose();
    }

    private void ListenForActivation()
    {
        while (!_disposed)
        {
            try
            {
                if (_activationEvent?.WaitOne() == true && !_disposed)
                {
                    ActivationRequested?.Invoke(this, EventArgs.Empty);
                }
            }
            catch (ObjectDisposedException)
            {
                return;
            }
        }
    }
}
