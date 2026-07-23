using MomentumHunter.Contracts;

namespace MomentumHunter.Application;

public interface ICandidateStoryWorkspaceClient
{
    Task<CandidateStorySnapshot> GetSnapshotAsync(
        string symbol,
        CancellationToken cancellationToken = default);
}
