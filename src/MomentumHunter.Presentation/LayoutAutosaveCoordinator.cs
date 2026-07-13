using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed class LayoutAutosaveCoordinator
{
    private readonly IWorkspaceLayoutStore _store;
    private readonly Func<WorkspaceLayoutSnapshot> _snapshotFactory;
    private readonly TimeSpan _delay;
    private readonly object _sync = new();
    private CancellationTokenSource? _pendingSave;

    public LayoutAutosaveCoordinator(
        IWorkspaceLayoutStore store,
        Func<WorkspaceLayoutSnapshot> snapshotFactory,
        TimeSpan? delay = null)
    {
        _store = store;
        _snapshotFactory = snapshotFactory;
        _delay = delay ?? TimeSpan.FromMilliseconds(450);
    }

    public void RequestSave()
    {
        CancellationTokenSource current;
        lock (_sync)
        {
            _pendingSave?.Cancel();
            current = new CancellationTokenSource();
            _pendingSave = current;
        }

        _ = SaveAfterDelayAsync(current);
    }

    public async Task FlushAsync(CancellationToken cancellationToken = default)
    {
        lock (_sync)
        {
            _pendingSave?.Cancel();
            _pendingSave = null;
        }

        await _store.SaveAsync(_snapshotFactory(), cancellationToken);
    }

    private async Task SaveAfterDelayAsync(CancellationTokenSource request)
    {
        try
        {
            await Task.Delay(_delay, request.Token);
            await _store.SaveAsync(_snapshotFactory(), request.Token);
        }
        catch (OperationCanceledException)
        {
            // A newer layout edit superseded this pending snapshot.
        }
        finally
        {
            lock (_sync)
            {
                if (ReferenceEquals(_pendingSave, request))
                {
                    _pendingSave = null;
                }
            }

            request.Dispose();
        }
    }
}
