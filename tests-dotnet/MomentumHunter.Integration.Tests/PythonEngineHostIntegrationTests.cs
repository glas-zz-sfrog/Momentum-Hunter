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
            Assert.DoesNotContain("submit_order", first.Capabilities);

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
            await WaitUntilAsync(() => !File.Exists(Path.Combine(stateDirectory, "python-engine-endpoint.json")));
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
