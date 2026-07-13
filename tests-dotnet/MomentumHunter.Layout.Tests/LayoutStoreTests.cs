using Microsoft.Data.Sqlite;
using MomentumHunter.Contracts;
using MomentumHunter.Infrastructure;

namespace MomentumHunter.Layout.Tests;

public sealed class LayoutStoreTests : IDisposable
{
    private readonly string _temporaryDirectory = Path.Combine(Path.GetTempPath(), "momentum-hunter-layout-tests", Guid.NewGuid().ToString("N"));

    [Fact]
    public void LayoutSerializationRoundTripsAndExcludesAuthorizationMaterial()
    {
        var snapshot = CreateSnapshot("NVDA", DateTimeOffset.Parse("2026-07-13T14:30:00Z")) with
        {
            DockLayoutXml = "<LayoutRoot><LayoutPanel Orientation=\"Horizontal\" /></LayoutRoot>",
            WindowBounds = new RectGeometry(120, 80, 1440, 920),
            ActivityExpanded = true,
            WindowState = WindowDisplayState.Maximized,
        };
        var sealedSnapshot = LayoutIntegrity.Seal(snapshot);

        var json = LayoutIntegrity.Serialize(sealedSnapshot);
        var roundTripped = LayoutIntegrity.Deserialize(json);

        Assert.NotNull(roundTripped);
        Assert.True(LayoutIntegrity.IsValid(roundTripped!));
        Assert.Equal("NVDA", roundTripped.SelectedSymbol);
        Assert.Equal(snapshot.DockLayoutXml, roundTripped.DockLayoutXml);
        Assert.Equal(snapshot.WindowBounds, roundTripped.WindowBounds);
        Assert.True(roundTripped.ActivityExpanded);
        Assert.Equal(WindowDisplayState.Maximized, roundTripped.WindowState);
        Assert.DoesNotContain("authorization", json, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("credential", json, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("token", json, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void InvalidChecksumIsRejected()
    {
        var snapshot = LayoutIntegrity.Seal(CreateSnapshot("NVDA", DateTimeOffset.UtcNow));

        Assert.False(LayoutIntegrity.IsValid(snapshot with { SelectedSymbol = "PLTR" }));
    }

    [Fact]
    public async Task StoreFallsBackToPreviousValidRevision()
    {
        var path = Path.Combine(_temporaryDirectory, "layouts.db");
        var store = new SqliteWorkspaceLayoutStore(path);
        var first = CreateSnapshot("NVDA", DateTimeOffset.Parse("2026-07-13T14:00:00Z"));
        var second = CreateSnapshot("PLTR", DateTimeOffset.Parse("2026-07-13T15:00:00Z"));
        await store.SaveAsync(first);
        await store.SaveAsync(second);

        await using (var connection = new SqliteConnection($"Data Source={path}"))
        {
            await connection.OpenAsync();
            await using var command = connection.CreateCommand();
            command.CommandText = "UPDATE workstation_layout_snapshots SET payload_json = REPLACE(payload_json, 'PLTR', 'AMD') WHERE revision_id = $id";
            command.Parameters.AddWithValue("$id", second.RevisionId.ToString("D"));
            await command.ExecuteNonQueryAsync();
        }

        var restored = await store.LoadLatestValidAsync(WorkspaceKind.Live);

        Assert.NotNull(restored);
        Assert.Equal("NVDA", restored!.SelectedSymbol);
    }

    [Fact]
    public async Task StoreRetainsTenAutomaticSnapshotsPerWorkspace()
    {
        var store = new SqliteWorkspaceLayoutStore(Path.Combine(_temporaryDirectory, "retention.db"));
        var start = DateTimeOffset.Parse("2026-07-13T10:00:00Z");
        for (var index = 0; index < 12; index++)
        {
            await store.SaveAsync(CreateSnapshot($"S{index}", start.AddMinutes(index)));
        }

        var snapshots = await store.ListAsync(WorkspaceKind.Live);

        Assert.Equal(10, snapshots.Count);
        Assert.Equal("S11", snapshots[0].SelectedSymbol);
    }

    [Fact]
    public void MissingMonitorRecoveryMovesFloatingPaneToPrimaryVisibleArea()
    {
        var layout = CreateSnapshot("NVDA", DateTimeOffset.UtcNow).Panes[0] with
        {
            DockRegion = DockRegion.Floating,
            DisplayKey = "MissingDisplay",
            FloatingBounds = new RectGeometry(4800, 1800, 1200, 900),
        };
        var displays = new[] { new DisplayGeometry("Primary", new RectGeometry(0, 0, 1920, 1040), 1.0) };

        var recovered = MonitorRecovery.Recover(layout, displays);

        Assert.Equal("Primary", recovered.DisplayKey);
        Assert.NotNull(recovered.FloatingBounds);
        Assert.InRange(recovered.FloatingBounds!.X, 0, 1440);
        Assert.InRange(recovered.FloatingBounds.Y, 0, 720);
    }

    public void Dispose()
    {
        SqliteConnection.ClearAllPools();
        if (Directory.Exists(_temporaryDirectory))
        {
            Directory.Delete(_temporaryDirectory, recursive: true);
        }
    }

    private static WorkspaceLayoutSnapshot CreateSnapshot(string symbol, DateTimeOffset createdAt)
    {
        var panes = new[]
        {
            new PaneLayout(Guid.NewGuid(), PaneKind.Chart, "Chart", LinkGroup.A, symbol, "5m", false, true, DockRegion.Center, 0, null, null),
        };
        return new WorkspaceLayoutSnapshot(1, WorkspaceKind.Live, Guid.NewGuid(), createdAt, false, null, symbol, "5m", panes, string.Empty);
    }
}
