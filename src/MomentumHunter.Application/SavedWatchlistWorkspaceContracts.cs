using MomentumHunter.Contracts;

namespace MomentumHunter.Application;

/// <summary>
/// Supplies the latest persisted saved-watchlist artifact without exposing
/// candidate selection, review, planning, scoring, alert, or execution actions.
/// </summary>
public interface ISavedWatchlistWorkspaceClient
{
    Task<SavedWatchlistSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default);
}
