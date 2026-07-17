using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.EngineBridge;

/// <summary>
/// WPF-side lifecycle adapter. The canonical collection loop remains in the independent Python host.
/// </summary>
public sealed class RemoteBackgroundCollectionService : IBackgroundCollectionService
{
    private readonly object _sync = new();
    private readonly IPythonEngineHostConnection _connection;
    private readonly TimeProvider _timeProvider;
    private readonly TimeSpan _refreshInterval;
    private CancellationTokenSource? _refreshCancellation;
    private Task? _refreshTask;
    private BackgroundCollectionStatus _status = new(
        BackgroundCollectionState.Starting,
        null,
        0,
        0,
        "Connecting to the local Python Engine Host.");
    private bool _started;
    private bool _stopped;

    public RemoteBackgroundCollectionService(
        IPythonEngineHostConnection connection,
        TimeProvider? timeProvider = null,
        TimeSpan? refreshInterval = null)
    {
        _connection = connection;
        _timeProvider = timeProvider ?? TimeProvider.System;
        _refreshInterval = refreshInterval ?? TimeSpan.FromSeconds(5);
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

    public async Task StartAsync(CancellationToken cancellationToken = default)
    {
        lock (_sync)
        {
            if (_started)
            {
                return;
            }

            _started = true;
        }

        try
        {
            var snapshot = await _connection.EnsureConnectedAsync(cancellationToken);
            ApplySnapshot(snapshot, "Connected to the local Python Engine Host.");
            _refreshCancellation = new CancellationTokenSource();
            _refreshTask = Task.Run(() => RefreshLoopAsync(_refreshCancellation.Token), CancellationToken.None);
        }
        catch (Exception exception)
        {
            ApplyConnectionFailure(exception);
        }
    }

    public async Task PauseAsync(CancellationToken cancellationToken = default) =>
        await SendLifecycleCommandAsync(PythonEngineHostProtocol.PauseCollection, cancellationToken);

    public async Task ResumeAsync(CancellationToken cancellationToken = default) =>
        await SendLifecycleCommandAsync(PythonEngineHostProtocol.ResumeCollection, cancellationToken);

    public async Task<CollectionCycleResult> RunScanNowAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var result = await _connection.SendCommandAsync(
                PythonEngineHostProtocol.RunCollectionCycle,
                Guid.NewGuid().ToString("N"),
                cancellationToken);
            ApplySnapshot(result.Snapshot, result.Summary);
            return new CollectionCycleResult(result.Accepted, result.Summary, Status);
        }
        catch (Exception exception)
        {
            ApplyConnectionFailure(exception);
            return new CollectionCycleResult(false, "The Python Engine Host is unavailable.", Status);
        }
    }

    public async Task StopAsync(CancellationToken cancellationToken = default)
    {
        Task? refreshTask;
        lock (_sync)
        {
            if (_stopped)
            {
                return;
            }

            _stopped = true;
            refreshTask = _refreshTask;
        }

        _refreshCancellation?.Cancel();
        if (refreshTask is not null)
        {
            try
            {
                await refreshTask.WaitAsync(cancellationToken);
            }
            catch (OperationCanceledException) when (_refreshCancellation?.IsCancellationRequested == true)
            {
            }
        }

        try
        {
            var result = await _connection.SendCommandAsync(
                PythonEngineHostProtocol.ShutdownHost,
                Guid.NewGuid().ToString("N"),
                cancellationToken);
            ApplySnapshot(result.Snapshot, result.Summary);
        }
        catch (Exception exception)
        {
            ApplyStatus(new BackgroundCollectionStatus(
                BackgroundCollectionState.Stopping,
                Status.LastCompletedCycleAt,
                Status.MonitoredSymbolCount,
                Status.CycleCount,
                $"Stopping workstation lifecycle; Python Engine Host status is unavailable: {exception.Message}"));
        }
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync();
        _refreshCancellation?.Dispose();
    }

    private async Task SendLifecycleCommandAsync(string command, CancellationToken cancellationToken)
    {
        try
        {
            var result = await _connection.SendCommandAsync(command, Guid.NewGuid().ToString("N"), cancellationToken);
            ApplySnapshot(result.Snapshot, result.Summary);
        }
        catch (Exception exception)
        {
            ApplyConnectionFailure(exception);
        }
    }

    private async Task RefreshLoopAsync(CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(_refreshInterval, _timeProvider);
        try
        {
            while (await timer.WaitForNextTickAsync(cancellationToken))
            {
                try
                {
                    ApplySnapshot(await _connection.GetSnapshotAsync(cancellationToken), "Refreshed Python Engine Host status.");
                }
                catch (Exception exception)
                {
                    ApplyConnectionFailure(exception);
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
    }

    private void ApplySnapshot(PythonEngineHostSnapshot snapshot, string activity) =>
        ApplyStatus(
            new BackgroundCollectionStatus(
                ToBackgroundState(snapshot.Collection.State),
                snapshot.Collection.LastCompletedCycleAtUtc,
                snapshot.Collection.MonitoredSymbolCount,
                snapshot.Collection.CycleCount,
                snapshot.Collection.Detail),
            activity);

    private void ApplyConnectionFailure(Exception exception) =>
        ApplyStatus(
            new BackgroundCollectionStatus(
                BackgroundCollectionState.Blocked,
                Status.LastCompletedCycleAt,
                Status.MonitoredSymbolCount,
                Status.CycleCount,
                "The local Python Engine Host is unavailable. Open System Status for details."),
            $"Python Engine Host connection failed: {exception.GetType().Name}.");

    private void ApplyStatus(BackgroundCollectionStatus status, string? activity = null)
    {
        lock (_sync)
        {
            _status = status;
        }

        StatusChanged?.Invoke(status);
        if (!string.IsNullOrWhiteSpace(activity))
        {
            ActivityRecorded?.Invoke(new BackgroundCollectionActivity(_timeProvider.GetUtcNow(), activity, status.State));
        }
    }

    private static BackgroundCollectionState ToBackgroundState(string state) => state switch
    {
        "Healthy" => BackgroundCollectionState.Healthy,
        "Degraded" => BackgroundCollectionState.Degraded,
        "Paused" => BackgroundCollectionState.Paused,
        "Blocked" => BackgroundCollectionState.Blocked,
        "Stopping" => BackgroundCollectionState.Stopping,
        _ => BackgroundCollectionState.Starting,
    };
}
