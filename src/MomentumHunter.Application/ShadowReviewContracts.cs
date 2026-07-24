using MomentumHunter.Contracts;

namespace MomentumHunter.Application;

/// <summary>
/// Read-only review boundary for canonical prospective Shadow Trading evidence.
/// It deliberately exposes no create, advance, edit, broker, Paper, or Live command.
/// </summary>
public interface IShadowReviewClient
{
    Task<ShadowReviewSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default);
}
