using System.Diagnostics;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.EngineBridge;

public sealed record PythonEngineHostOptions(
    string StateDirectory,
    string WorkingDirectory,
    string PythonExecutable,
    TimeSpan LaunchTimeout,
    TimeSpan RequestTimeout)
{
    public static PythonEngineHostOptions CreateDefault()
    {
        var stateDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "MomentumHunter",
            "python-engine-host");
        var workingDirectory = FindRepositoryRoot() ?? Directory.GetCurrentDirectory();
        var pythonExecutable = Environment.GetEnvironmentVariable("MOMENTUM_HUNTER_PYTHON_EXECUTABLE");
        var repositoryVirtualEnvironment = Path.Combine(workingDirectory, ".venv", "Scripts", "python.exe");
        return new PythonEngineHostOptions(
            stateDirectory,
            workingDirectory,
            string.IsNullOrWhiteSpace(pythonExecutable)
                ? File.Exists(repositoryVirtualEnvironment) ? repositoryVirtualEnvironment : "py"
                : pythonExecutable,
            TimeSpan.FromSeconds(20),
            TimeSpan.FromSeconds(5));
    }

    private static string? FindRepositoryRoot()
    {
        var configured = Environment.GetEnvironmentVariable("MOMENTUM_HUNTER_REPOSITORY_ROOT");
        var candidates = new[] { configured, Directory.GetCurrentDirectory(), AppContext.BaseDirectory }
            .Where(candidate => !string.IsNullOrWhiteSpace(candidate))
            .Select(candidate => new DirectoryInfo(Path.GetFullPath(candidate!)));
        foreach (var candidate in candidates)
        {
            for (var current = candidate; current is not null; current = current.Parent)
            {
                if (File.Exists(Path.Combine(current.FullName, "momentum_hunter", "engine_host.py")))
                {
                    return current.FullName;
                }
            }
        }

        return null;
    }
}

public interface IPythonEngineHostProcessLauncher
{
    Task LaunchAsync(PythonEngineHostOptions options, CancellationToken cancellationToken = default);
}

public sealed class PythonEngineHostProcessLauncher : IPythonEngineHostProcessLauncher
{
    public Task LaunchAsync(PythonEngineHostOptions options, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        Directory.CreateDirectory(options.StateDirectory);
        var startInfo = new ProcessStartInfo
        {
            FileName = options.PythonExecutable,
            WorkingDirectory = options.WorkingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        if (string.Equals(Path.GetFileNameWithoutExtension(options.PythonExecutable), "py", StringComparison.OrdinalIgnoreCase))
        {
            startInfo.ArgumentList.Add("-3");
        }
        startInfo.ArgumentList.Add("-m");
        startInfo.ArgumentList.Add("momentum_hunter.engine_host");
        startInfo.ArgumentList.Add("--state-directory");
        startInfo.ArgumentList.Add(options.StateDirectory);
        startInfo.Environment["PYTHONUTF8"] = "1";

        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("The Python Engine Host process could not be launched.");
        return Task.CompletedTask;
    }
}

public sealed class PythonEngineHostConnection : IPythonEngineHostConnection
{
    private const string EndpointFilename = "python-engine-endpoint.json";
    private static readonly SemaphoreSlim LaunchGate = new(1, 1);
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };

    private readonly PythonEngineHostOptions _options;
    private readonly IPythonEngineHostProcessLauncher _launcher;

    public PythonEngineHostConnection(PythonEngineHostOptions options, IPythonEngineHostProcessLauncher? launcher = null)
    {
        _options = options;
        _launcher = launcher ?? new PythonEngineHostProcessLauncher();
    }

    public async Task<PythonEngineHostSnapshot> EnsureConnectedAsync(CancellationToken cancellationToken = default)
    {
        if (await TryGetSnapshotAsync(cancellationToken) is { } existing)
        {
            return existing;
        }

        await LaunchGate.WaitAsync(cancellationToken);
        try
        {
            if (await TryGetSnapshotAsync(cancellationToken) is { } discovered)
            {
                return discovered;
            }

            await _launcher.LaunchAsync(_options, cancellationToken);
            var deadline = DateTimeOffset.UtcNow + _options.LaunchTimeout;
            Exception? lastError = null;
            while (DateTimeOffset.UtcNow < deadline)
            {
                cancellationToken.ThrowIfCancellationRequested();
                try
                {
                    if (await TryGetSnapshotAsync(cancellationToken) is { } launched)
                    {
                        return launched;
                    }
                }
                catch (Exception exception) when (exception is IOException or SocketException or JsonException)
                {
                    lastError = exception;
                }

                await Task.Delay(TimeSpan.FromMilliseconds(125), cancellationToken);
            }

            throw new InvalidOperationException(
                "The Python Engine Host did not publish a usable local endpoint before the launch timeout.",
                lastError);
        }
        finally
        {
            LaunchGate.Release();
        }
    }

    public async Task<PythonEngineHostSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default)
    {
        var endpoint = await LoadEndpointAsync(cancellationToken)
            ?? throw new InvalidOperationException("No Python Engine Host endpoint is currently available.");
        var result = await SendRequestAsync(
            endpoint,
            PythonEngineHostProtocol.GetHostSnapshot,
            Guid.NewGuid().ToString("N"),
            new Dictionary<string, string>(),
            cancellationToken);
        if (!result.Accepted)
        {
            throw new InvalidOperationException($"Python Engine Host rejected its snapshot request: {result.Code}.");
        }

        return result.Snapshot;
    }

    public async Task<PythonEngineHostCommandResult> SendCommandAsync(
        string command,
        string commandId,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(commandId))
        {
            throw new ArgumentException("A stable command ID is required.", nameof(commandId));
        }

        var endpoint = await LoadEndpointAsync(cancellationToken)
            ?? throw new InvalidOperationException("No Python Engine Host endpoint is currently available.");
        return await SendRequestAsync(endpoint, command, commandId, new Dictionary<string, string>(), cancellationToken);
    }

    public async Task<JsonElement> GetReadOnlyWorkspaceSnapshotAsync(CancellationToken cancellationToken = default)
    {
        await EnsureConnectedAsync(cancellationToken);
        var result = await SendCommandAsync(
            PythonEngineHostProtocol.GetReadOnlyWorkspaceSnapshot,
            Guid.NewGuid().ToString("N"),
            cancellationToken);
        if (!result.Accepted || result.Payload is null)
        {
            throw new InvalidOperationException($"The Python Engine Host did not provide a read-only workspace snapshot: {result.Code}.");
        }

        return result.Payload.Value.Clone();
    }

    public async Task<JsonElement> GetSimulationWorkspaceSnapshotAsync(CancellationToken cancellationToken = default)
    {
        await EnsureConnectedAsync(cancellationToken);
        var result = await SendCommandWithArgumentsAsync(
            PythonEngineHostProtocol.GetSimulationWorkspaceSnapshot,
            Guid.NewGuid().ToString("N"),
            new Dictionary<string, string>(),
            cancellationToken);
        if (!result.Accepted || result.Payload is null)
        {
            throw new InvalidOperationException($"The Python Engine Host did not provide a simulation workspace snapshot: {result.Code}.");
        }

        return result.Payload.Value.Clone();
    }

    public async Task<JsonElement> RunSimulationAsync(string symbol, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(symbol))
        {
            throw new ArgumentException("A symbol is required for FakeBroker simulation.", nameof(symbol));
        }

        await EnsureConnectedAsync(cancellationToken);
        var result = await SendCommandWithArgumentsAsync(
            PythonEngineHostProtocol.RunSimulation,
            Guid.NewGuid().ToString("N"),
            new Dictionary<string, string>(StringComparer.Ordinal) { ["symbol"] = symbol.Trim().ToUpperInvariant() },
            cancellationToken);
        if (!result.Accepted || result.Payload is null)
        {
            throw new InvalidOperationException($"The Python Engine Host did not complete the FakeBroker simulation: {result.Code}.");
        }

        return result.Payload.Value.Clone();
    }

    private async Task<PythonEngineHostCommandResult> SendCommandWithArgumentsAsync(
        string command,
        string commandId,
        IReadOnlyDictionary<string, string> arguments,
        CancellationToken cancellationToken)
    {
        var endpoint = await LoadEndpointAsync(cancellationToken)
            ?? throw new InvalidOperationException("No Python Engine Host endpoint is currently available.");
        return await SendRequestAsync(endpoint, command, commandId, arguments, cancellationToken);
    }

    private async Task<PythonEngineHostSnapshot?> TryGetSnapshotAsync(CancellationToken cancellationToken)
    {
        try
        {
            return await GetSnapshotAsync(cancellationToken);
        }
        catch (InvalidOperationException)
        {
            return null;
        }
        catch (SocketException)
        {
            return null;
        }
        catch (IOException)
        {
            return null;
        }
        catch (JsonException)
        {
            return null;
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            return null;
        }
    }

    private async Task<PythonEngineHostEndpoint?> LoadEndpointAsync(CancellationToken cancellationToken)
    {
        var endpointPath = Path.Combine(_options.StateDirectory, EndpointFilename);
        if (!File.Exists(endpointPath))
        {
            return null;
        }

        await using var stream = File.OpenRead(endpointPath);
        var endpoint = await JsonSerializer.DeserializeAsync<PythonEngineHostEndpoint>(stream, SerializerOptions, cancellationToken);
        if (endpoint is null || endpoint.ProtocolVersion != PythonEngineHostProtocol.Version || endpoint.Address != "127.0.0.1")
        {
            throw new InvalidOperationException("The Python Engine Host endpoint descriptor is invalid or is not loopback-only.");
        }
        if (endpoint.Port is < 1024 or > 65535 || string.IsNullOrWhiteSpace(endpoint.AccessToken))
        {
            throw new InvalidOperationException("The Python Engine Host endpoint descriptor is incomplete.");
        }

        return endpoint;
    }

    private async Task<PythonEngineHostCommandResult> SendRequestAsync(
        PythonEngineHostEndpoint endpoint,
        string command,
        string commandId,
        IReadOnlyDictionary<string, string> arguments,
        CancellationToken cancellationToken)
    {
        var requestId = Guid.NewGuid().ToString("N");
        var request = new PythonEngineHostRequest(
            PythonEngineHostProtocol.Version,
            requestId,
            endpoint.AccessToken,
            command,
            commandId,
            arguments);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(_options.RequestTimeout);
        using var client = new TcpClient();
        await client.ConnectAsync(endpoint.Address, endpoint.Port, timeout.Token);
        await using var stream = client.GetStream();
        var payload = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(request, SerializerOptions) + "\n");
        await stream.WriteAsync(payload, timeout.Token);
        await stream.FlushAsync(timeout.Token);
        using var reader = new StreamReader(stream, Encoding.UTF8, leaveOpen: true);
        var responseLine = await reader.ReadLineAsync(timeout.Token);
        if (string.IsNullOrWhiteSpace(responseLine))
        {
            throw new IOException("The Python Engine Host returned no response.");
        }

        var response = JsonSerializer.Deserialize<PythonEngineHostResponse>(responseLine, SerializerOptions)
            ?? throw new JsonException("The Python Engine Host response was empty.");
        if (response.ProtocolVersion != PythonEngineHostProtocol.Version || response.RequestId != requestId || response.Result?.Snapshot is null)
        {
            throw new JsonException("The Python Engine Host response did not satisfy the versioned contract.");
        }

        return new PythonEngineHostCommandResult(
            response.Accepted,
            response.Result.Code,
            response.Result.Summary,
            response.Result.Snapshot,
            response.Result.Payload?.Clone());
    }

    private sealed record PythonEngineHostEndpoint(
        int SchemaVersion,
        string ProtocolVersion,
        string HostInstanceId,
        int ProcessId,
        DateTimeOffset StartedAtUtc,
        string Address,
        int Port,
        string AccessToken);

    private sealed record PythonEngineHostRequest(
        string ProtocolVersion,
        string RequestId,
        string AccessToken,
        string Command,
        string CommandId,
        IReadOnlyDictionary<string, string> Arguments);

    private sealed record PythonEngineHostResponse(
        string ProtocolVersion,
        string RequestId,
        bool Accepted,
        PythonEngineHostResult? Result);

    private sealed record PythonEngineHostResult(
        string Code,
        string Summary,
        PythonEngineHostSnapshot? Snapshot,
        JsonElement? Payload);
}
