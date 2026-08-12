using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;

namespace MomentumHunter.Integration.Tests;

public sealed class PythonEngineHostIntegrationTests
{
    [Fact]
    public void DefaultHostOptionsPreferTheRepositoryVirtualEnvironmentWhenAvailable()
    {
        var root = FindRepositoryRoot();
        var configuredPython = Environment.GetEnvironmentVariable("MOMENTUM_HUNTER_PYTHON_EXECUTABLE");
        var virtualEnvironmentPython = Path.Combine(root, ".venv", "Scripts", "python.exe");
        var options = PythonEngineHostOptions.CreateDefault();

        Assert.Equal(root, options.WorkingDirectory);
        Assert.Contains("python-engine-host", options.StateDirectory, StringComparison.OrdinalIgnoreCase);
        if (string.IsNullOrWhiteSpace(configuredPython) && File.Exists(virtualEnvironmentPython))
        {
            Assert.Equal(virtualEnvironmentPython, options.PythonExecutable);
        }
    }

    [Fact]
    public async Task WpfBoundaryLaunchesReconnectsAndDeliberatelyStopsOnePythonHost()
    {
        var stateDirectory = Path.Combine(Path.GetTempPath(), "MomentumHunter.R008.Tests", Guid.NewGuid().ToString("N"));
        var options = new PythonEngineHostOptions(
            stateDirectory,
            FindRepositoryRoot(),
            FindPythonExecutable(),
            TimeSpan.FromSeconds(20),
            TimeSpan.FromSeconds(5));
        var firstConnection = new PythonEngineHostConnection(options);
        var secondConnection = new PythonEngineHostConnection(options);

        try
        {
            var connected = await Task.WhenAll(
                firstConnection.EnsureConnectedAsync(),
                secondConnection.EnsureConnectedAsync());
            var first = connected[0];
            var second = connected[1];
            var reconnected = await secondConnection.GetSnapshotAsync();

            Assert.Equal(PythonEngineHostProtocol.Version, first.Identity.ProtocolVersion);
            Assert.Equal("loopback-tcp", first.Identity.Transport);
            Assert.Equal(first.Identity.HostInstanceId, second.Identity.HostInstanceId);
            Assert.Equal(first.Identity.HostInstanceId, reconnected.Identity.HostInstanceId);
            Assert.Contains(PythonEngineHostProtocol.PauseCollection, first.Capabilities);
            Assert.Contains(PythonEngineHostProtocol.GetReadOnlyWorkspaceSnapshot, first.Capabilities);
            Assert.Contains(PythonEngineHostProtocol.GetSimulationWorkspaceSnapshot, first.Capabilities);
            Assert.Contains(PythonEngineHostProtocol.GetShadowTradingSnapshot, first.Capabilities);
            Assert.Contains(PythonEngineHostProtocol.GetChartSnapshot, first.Capabilities);
            Assert.Contains(PythonEngineHostProtocol.GetTechnicalResearchSnapshot, first.Capabilities);
            Assert.Contains(PythonEngineHostProtocol.GetSavedWatchlistSnapshot, first.Capabilities);
            Assert.Contains(PythonEngineHostProtocol.GetDailyWorkflowSnapshot, first.Capabilities);
            Assert.Contains(PythonEngineHostProtocol.GetCandidateStorySnapshot, first.Capabilities);
            Assert.Contains(PythonEngineHostProtocol.GetResearchMaturitySnapshot, first.Capabilities);
            Assert.Contains(PythonEngineHostProtocol.RunSimulation, first.Capabilities);
            Assert.DoesNotContain("submit_order", first.Capabilities);

            var readOnlyWorkspacePayload = await firstConnection.GetReadOnlyWorkspaceSnapshotAsync();
            Assert.Equal(2, readOnlyWorkspacePayload.GetProperty("schemaVersion").GetInt32());
            Assert.False(readOnlyWorkspacePayload.GetProperty("planningAvailable").GetBoolean());
            Assert.True(readOnlyWorkspacePayload.TryGetProperty("candidates", out _));
            Assert.True(readOnlyWorkspacePayload.TryGetProperty("health", out _));
            Assert.True(readOnlyWorkspacePayload.TryGetProperty("replay", out _));

            var chartPayload = await firstConnection.GetChartSnapshotAsync("ZZZNOTREAL", "Daily");
            Assert.Equal(2, chartPayload.GetProperty("schemaVersion").GetInt32());
            Assert.Equal("ZZZNOTREAL", chartPayload.GetProperty("symbol").GetString());
            Assert.Equal("Daily", chartPayload.GetProperty("interval").GetString());
            Assert.Equal("UNAVAILABLE", chartPayload.GetProperty("state").GetString());
            Assert.Empty(chartPayload.GetProperty("candles").EnumerateArray());
            Assert.Equal(
                "UNAVAILABLE",
                chartPayload.GetProperty("quality").GetProperty("status").GetString());
            Assert.Contains(
                "No simulated, legacy, or cross-timeframe fallback",
                chartPayload.GetProperty("summary").GetString(),
                StringComparison.Ordinal);

            var researchPayload = await firstConnection.GetTechnicalResearchSnapshotAsync("ZZZNOTREAL");
            Assert.Equal(1, researchPayload.GetProperty("schemaVersion").GetInt32());
            Assert.Equal("ZZZNOTREAL", researchPayload.GetProperty("symbol").GetString());
            Assert.Contains(
                researchPayload.GetProperty("state").GetString(),
                new[] { "UNAVAILABLE", "EMPTY" });
            Assert.Empty(researchPayload.GetProperty("events").EnumerateArray());
            Assert.Empty(researchPayload.GetProperty("studies").EnumerateArray());

            var savedWatchlistPayload = await firstConnection.GetSavedWatchlistSnapshotAsync();
            Assert.Equal(1, savedWatchlistPayload.GetProperty("schemaVersion").GetInt32());
            Assert.Contains(
                savedWatchlistPayload.GetProperty("state").GetString(),
                new[] { "AVAILABLE", "PARTIAL", "STALE", "EMPTY", "UNAVAILABLE" });
            var savedWatchlistItems = savedWatchlistPayload.GetProperty("items").EnumerateArray().ToArray();
            var displayedItemCount = savedWatchlistPayload.GetProperty("displayedItemCount").GetInt32();
            var totalItemCount = savedWatchlistPayload.GetProperty("totalItemCount").GetInt32();
            Assert.Equal(savedWatchlistItems.Length, displayedItemCount);
            Assert.True(totalItemCount >= displayedItemCount);

            var dailyWorkflowPayload = await firstConnection.GetDailyWorkflowSnapshotAsync();
            Assert.Equal(1, dailyWorkflowPayload.GetProperty("schemaVersion").GetInt32());
            Assert.True(dailyWorkflowPayload.GetProperty("readOnly").GetBoolean());
            Assert.True(dailyWorkflowPayload.TryGetProperty("state", out _));
            Assert.True(dailyWorkflowPayload.TryGetProperty("nextAction", out _));
            Assert.True(dailyWorkflowPayload.TryGetProperty("steps", out _));

            var candidateStoryPayload = await firstConnection.GetCandidateStorySnapshotAsync("ZZZNOTREAL");
            Assert.Equal(1, candidateStoryPayload.GetProperty("schemaVersion").GetInt32());
            Assert.Equal("ZZZNOTREAL", candidateStoryPayload.GetProperty("symbol").GetString());
            Assert.Equal("EMPTY", candidateStoryPayload.GetProperty("state").GetString());
            Assert.True(candidateStoryPayload.GetProperty("readOnly").GetBoolean());
            Assert.Empty(candidateStoryPayload.GetProperty("points").EnumerateArray());

            var researchMaturityPayload =
                await firstConnection.GetResearchMaturitySnapshotAsync();
            Assert.Equal(
                1,
                researchMaturityPayload.GetProperty("schemaVersion").GetInt32());
            Assert.True(
                researchMaturityPayload.GetProperty("researchOnly").GetBoolean());
            Assert.True(
                researchMaturityPayload.GetProperty("readOnly").GetBoolean());
            Assert.False(
                researchMaturityPayload
                    .GetProperty("strategyChangeRecommendationsAllowed")
                    .GetBoolean());
            Assert.Equal(
                "LOCKED",
                researchMaturityPayload
                    .GetProperty("strategyOptimizationStatus")
                    .GetString());

            var simulationWorkspacePayload = await firstConnection.GetSimulationWorkspaceSnapshotAsync();
            Assert.Equal("SIMULATION_ONLY_FAKE_BROKER", simulationWorkspacePayload.GetProperty("mode").GetString());
            Assert.True(simulationWorkspacePayload.TryGetProperty("plans", out _));
            var shadowPayload = await firstConnection.GetShadowTradingSnapshotAsync();
            Assert.Equal("PAPER SHADOW / NONTRANSMITTING", shadowPayload.GetProperty("mode").GetString());
            Assert.False(shadowPayload.GetProperty("transmitting").GetBoolean());
            Assert.True(shadowPayload.TryGetProperty("reviewTrades", out _));
            Assert.True(shadowPayload.TryGetProperty("sample", out _));
            Assert.True(shadowPayload.TryGetProperty("reviewMetrics", out _));
            var unavailableSimulationPayload = await firstConnection.RunSimulationAsync("ZZZNOTAREALPERSISTEDPLAN");
            Assert.Equal("Unavailable", unavailableSimulationPayload.GetProperty("state").GetString());
            Assert.Equal([], unavailableSimulationPayload.GetProperty("ledgerEvents").EnumerateArray().ToArray());

            var paused = await firstConnection.SendCommandAsync(PythonEngineHostProtocol.PauseCollection, "pause-once");
            var repeatedPause = await firstConnection.SendCommandAsync(PythonEngineHostProtocol.PauseCollection, "pause-once");
            var resumed = await secondConnection.SendCommandAsync(PythonEngineHostProtocol.ResumeCollection, "resume-once");

            Assert.True(paused.Accepted);
            Assert.True(repeatedPause.Accepted);
            Assert.Equal(paused.Code, repeatedPause.Code);
            Assert.Equal(paused.Snapshot.Identity.HostInstanceId, repeatedPause.Snapshot.Identity.HostInstanceId);
            Assert.Equal(paused.Snapshot.Collection.State, repeatedPause.Snapshot.Collection.State);
            Assert.Equal("Paused", paused.Snapshot.Collection.State);
            Assert.True(resumed.Accepted);
            Assert.Equal("Healthy", resumed.Snapshot.Collection.State);

            var shutdown = await firstConnection.SendCommandAsync(PythonEngineHostProtocol.ShutdownHost, "shutdown-once");
            Assert.True(shutdown.Accepted);
            Assert.Equal("SHUTDOWN_REQUESTED", shutdown.Code);
            await WaitUntilAsync(() =>
                !File.Exists(Path.Combine(stateDirectory, "python-engine-endpoint.json"))
                && !File.Exists(Path.Combine(stateDirectory, "python-engine-host.lock")));
            Assert.False(File.Exists(Path.Combine(stateDirectory, "python-engine-host.lock")));
        }
        finally
        {
            if (File.Exists(Path.Combine(stateDirectory, "python-engine-endpoint.json")))
            {
                try
                {
                    await firstConnection.SendCommandAsync(PythonEngineHostProtocol.ShutdownHost, Guid.NewGuid().ToString("N"));
                    await WaitUntilAsync(() => !File.Exists(Path.Combine(stateDirectory, "python-engine-endpoint.json")));
                }
                catch (Exception)
                {
                    // A failed test must not conceal its primary assertion with cleanup noise.
                }
            }

            if (Directory.Exists(stateDirectory))
            {
                Directory.Delete(stateDirectory, recursive: true);
            }
        }
    }

    [Fact]
    public async Task RemoteLifecycleAdapterUsesOnlyHostLifecycleCommands()
    {
        var connection = new RecordingHostConnection();
        await using var service = new RemoteBackgroundCollectionService(connection, refreshInterval: TimeSpan.FromDays(1));
        var observedStates = new List<BackgroundCollectionState>();
        service.StatusChanged += status => observedStates.Add(status.State);

        await service.StartAsync();
        await service.PauseAsync();
        var blockedCycle = await service.RunScanNowAsync();
        await service.ResumeAsync();
        var completedCycle = await service.RunScanNowAsync();
        await service.StopAsync();

        Assert.False(blockedCycle.Completed);
        Assert.True(completedCycle.Completed);
        Assert.Contains(PythonEngineHostProtocol.PauseCollection, connection.Commands);
        Assert.Contains(PythonEngineHostProtocol.ResumeCollection, connection.Commands);
        Assert.Contains(PythonEngineHostProtocol.RunCollectionCycle, connection.Commands);
        Assert.Contains(PythonEngineHostProtocol.ShutdownHost, connection.Commands);
        Assert.DoesNotContain(connection.Commands, command => command.Contains("order", StringComparison.OrdinalIgnoreCase));
        Assert.Contains(BackgroundCollectionState.Healthy, observedStates);
        Assert.Contains(BackgroundCollectionState.Paused, observedStates);
        Assert.Equal(BackgroundCollectionState.Stopping, service.Status.State);
    }

    [Fact]
    public async Task RemoteLifecycleAdapterReportsAnUnavailableHostWithoutCrashingTheWorkstation()
    {
        await using var service = new RemoteBackgroundCollectionService(new UnavailableHostConnection());

        await service.StartAsync();

        Assert.Equal(BackgroundCollectionState.Blocked, service.Status.State);
        Assert.Contains("unavailable", service.Status.Detail, StringComparison.OrdinalIgnoreCase);
    }

    private static string FindRepositoryRoot()
    {
        foreach (var startingPath in new[] { Directory.GetCurrentDirectory(), AppContext.BaseDirectory })
        {
            for (var current = new DirectoryInfo(startingPath); current is not null; current = current.Parent)
            {
                if (File.Exists(Path.Combine(current.FullName, "MomentumHunter.Workstation.sln")))
                {
                    return current.FullName;
                }
            }
        }

        throw new InvalidOperationException("Could not locate the Momentum Hunter repository root for the Python host test.");
    }

    private static string FindPythonExecutable()
    {
        var virtualEnvironmentPython = Path.Combine(FindRepositoryRoot(), ".venv", "Scripts", "python.exe");
        return File.Exists(virtualEnvironmentPython) ? virtualEnvironmentPython : "py";
    }

    private static async Task WaitUntilAsync(Func<bool> condition)
    {
        var timeout = DateTimeOffset.UtcNow + TimeSpan.FromSeconds(10);
        while (DateTimeOffset.UtcNow < timeout)
        {
            if (condition())
            {
                return;
            }

            await Task.Delay(100);
        }

        throw new TimeoutException("Timed out waiting for the Python Engine Host cleanup condition.");
    }

    private sealed class RecordingHostConnection : IPythonEngineHostConnection
    {
        private PythonEngineHostSnapshot _snapshot = Snapshot("Healthy", cycleCount: 0, paused: false);

        public List<string> Commands { get; } = [];

        public Task<PythonEngineHostSnapshot> EnsureConnectedAsync(CancellationToken cancellationToken = default) => Task.FromResult(_snapshot);

        public Task<PythonEngineHostSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) => Task.FromResult(_snapshot);

        public Task<PythonEngineHostCommandResult> SendCommandAsync(
            string command,
            string commandId,
            CancellationToken cancellationToken = default)
        {
            Commands.Add(command);
            var accepted = true;
            var code = "OK";
            var summary = "Host lifecycle command completed.";
            if (command == PythonEngineHostProtocol.PauseCollection)
            {
                _snapshot = Snapshot("Paused", _snapshot.Collection.CycleCount, paused: true);
                code = "PAUSED";
            }
            else if (command == PythonEngineHostProtocol.ResumeCollection)
            {
                _snapshot = Snapshot("Healthy", _snapshot.Collection.CycleCount, paused: false);
                code = "RESUMED";
            }
            else if (command == PythonEngineHostProtocol.RunCollectionCycle && _snapshot.Collection.IsPaused)
            {
                accepted = false;
                code = "COLLECTION_PAUSED";
                summary = "Background collection is paused.";
            }
            else if (command == PythonEngineHostProtocol.RunCollectionCycle)
            {
                _snapshot = Snapshot("Healthy", _snapshot.Collection.CycleCount + 1, paused: false);
                code = "COLLECTION_COMPLETED";
                summary = "Background collection cycle completed.";
            }
            else if (command == PythonEngineHostProtocol.ShutdownHost)
            {
                _snapshot = Snapshot("Stopping", _snapshot.Collection.CycleCount, paused: false);
                code = "SHUTDOWN_REQUESTED";
            }

            return Task.FromResult(new PythonEngineHostCommandResult(accepted, code, summary, _snapshot));
        }

        private static PythonEngineHostSnapshot Snapshot(string state, int cycleCount, bool paused) => new(
            1,
            new PythonEngineHostIdentity(PythonEngineHostProtocol.Version, "test-host", 1234, DateTimeOffset.UtcNow, "loopback-tcp"),
            new PythonEngineHostHealthSnapshot(state, DateTimeOffset.UtcNow, "Test host state."),
            new PythonEngineCollectionSnapshot(state, paused, false, cycleCount, 5, null, null, "Test collection state."),
            [
                PythonEngineHostProtocol.GetHostSnapshot,
                PythonEngineHostProtocol.PauseCollection,
                PythonEngineHostProtocol.ResumeCollection,
                PythonEngineHostProtocol.RunCollectionCycle,
                PythonEngineHostProtocol.ShutdownHost,
            ]);
    }

    private sealed class UnavailableHostConnection : IPythonEngineHostConnection
    {
        public Task<PythonEngineHostSnapshot> EnsureConnectedAsync(CancellationToken cancellationToken = default) =>
            Task.FromException<PythonEngineHostSnapshot>(new IOException("Python process unavailable."));

        public Task<PythonEngineHostSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
            Task.FromException<PythonEngineHostSnapshot>(new IOException("Python process unavailable."));

        public Task<PythonEngineHostCommandResult> SendCommandAsync(
            string command,
            string commandId,
            CancellationToken cancellationToken = default) =>
            Task.FromException<PythonEngineHostCommandResult>(new IOException("Python process unavailable."));
    }
}
