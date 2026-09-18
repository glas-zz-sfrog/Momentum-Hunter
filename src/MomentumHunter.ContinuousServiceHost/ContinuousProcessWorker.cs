using System.Diagnostics;
using System.Text.Json;

namespace MomentumHunter.ContinuousServiceHost;

public sealed record ContinuousServiceOptions(
    string Role,
    string RepositoryRoot,
    string PythonExecutable,
    string ConfigPath,
    string ServiceName,
    string DisplayName,
    bool Qualification = false,
    bool ConsoleControl = false,
    int ShutdownSeconds = 30,
    string? QualificationConfigSha256 = null)
{
    public static ContinuousServiceOptions Create(IReadOnlyList<string> args)
    {
        var values = Parse(args);
        var role = values.GetValueOrDefault("--role")
            ?? throw new ArgumentException("--role is required.");
        if (role is not ("writer" or "runtime" or "science"))
        {
            throw new ArgumentException("--role must be writer, runtime or science.");
        }

        var repositoryRoot = Required(values, "--repository-root");
        var pythonExecutable = Required(values, "--python-executable");
        var configPath = Required(values, "--config");
        var suffix = char.ToUpperInvariant(role[0]) + role[1..];
        var instance = values.GetValueOrDefault("--instance", "production");
        var configBytes = File.ReadAllBytes(configPath);
        using var document = JsonDocument.Parse(configBytes);
        var config = document.RootElement;
        var targetOverride = ScienceQualificationTargets.ValidateOverrideMode(config);
        var qualification = false;
        var shutdownSeconds = 30;
        var name = $"MomentumHunterContinuous{suffix}";
        if (config.GetProperty("schemaVersion").GetInt32() == 2)
        {
            var mode = config.GetProperty("inputMode").GetString();
            var host = config.GetProperty("host");
            if (mode is not ("LIVE_PRODUCTION" or "OFFLINE_QUALIFICATION") ||
                host.GetProperty("instanceId").GetString() != instance)
                throw new ArgumentException("Explicit host input/instance binding is invalid.");
            qualification = mode == "OFFLINE_QUALIFICATION";
            if (qualification)
            {
                if (!System.Text.RegularExpressions.Regex.IsMatch(instance, "^qual-[a-z0-9][a-z0-9-]{0,31}$"))
                    throw new ArgumentException("Qualification identity is invalid.");
                name = $"MomentumHunterContinuous-{instance}-{suffix}";
                if (role == "writer" && host.GetProperty("science").GetProperty("custodyPolicy")
                    .TryGetProperty("actor_profile", out var actorProfile) && actorProfile.ValueKind != JsonValueKind.Null)
                {
                    if (actorProfile.GetProperty("writer").GetProperty("service_name").GetString() != name ||
                        actorProfile.GetProperty("profile").GetString() != "bounded-existing-scm-writer-v1")
                        throw new ArgumentException("Writer native launch profile does not bind its existing qualification target.");
                }
            }
            else if (instance != "production")
                throw new ArgumentException("Qualification cannot select production input.");
            if (host.GetProperty("services").GetProperty(role).GetString() != name)
                throw new ArgumentException("Service name does not match its instance.");
            if (role == "science" && !host.GetProperty("science").GetProperty("enabled").GetBoolean())
                throw new ArgumentException("Science role is disabled.");
            shutdownSeconds = host.GetProperty("shutdownSeconds").GetInt32();
            if (shutdownSeconds < 10 || shutdownSeconds > 120)
                throw new ArgumentException("Shutdown bound is invalid.");
        }
        else if (config.GetProperty("schemaVersion").GetInt32() != 1 || instance != "production" || role == "science" ||
            config.TryGetProperty("inputMode", out _) || config.TryGetProperty("host", out _))
            throw new ArgumentException("Unrecognized legacy host descriptor.");
        var consoleControl = values.GetValueOrDefault("--console-control", "false");
        if (consoleControl is not ("true" or "false") || (consoleControl == "true" && !qualification))
            throw new ArgumentException("Console control is restricted to offline qualification.");
        if (qualification && role == "writer" && consoleControl == "true")
            throw new ArgumentException("Writer qualification requires its actual SCM service, not an elevated peer process.");
        return new ContinuousServiceOptions(
            role,
            Path.GetFullPath(repositoryRoot),
            pythonExecutable,
            Path.GetFullPath(configPath),
            name,
            $"Momentum Hunter Continuous {suffix} (Research Only)", qualification,
            consoleControl == "true", shutdownSeconds,
            targetOverride ? Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(configBytes)).ToLowerInvariant() : null);
    }

    private static string Required(IReadOnlyDictionary<string, string> values, string name)
    {
        if (!values.TryGetValue(name, out var value) || string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException($"{name} requires a value.");
        }
        return value;
    }

    private static Dictionary<string, string> Parse(IReadOnlyList<string> args)
    {
        var allowed = new HashSet<string>(StringComparer.Ordinal)
        {
            "--role", "--repository-root", "--python-executable", "--config", "--instance", "--console-control"
        };
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        for (var index = 0; index < args.Count; index += 2)
        {
            if (index + 1 >= args.Count || !allowed.Contains(args[index]))
            {
                throw new ArgumentException("Continuous service arguments are malformed.");
            }
            if (!result.TryAdd(args[index], args[index + 1]))
            {
                throw new ArgumentException($"Duplicate service argument: {args[index]}");
            }
        }
        return result;
    }
}

public sealed class ContinuousProcessWorker(
    ContinuousServiceOptions options,
    ILogger<ContinuousProcessWorker> logger,
    IHostApplicationLifetime lifetime)
    : BackgroundService
{
    private Process? _process;
    private HostProcessGeneration? _generation;
    private int _lastExitCode;
    private DirectScienceImage? _writerImage;
    private static readonly TimeSpan[] RestartDelays =
    {
        TimeSpan.FromSeconds(5),
        TimeSpan.FromSeconds(15),
        TimeSpan.FromSeconds(60),
    };

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (options.Role == "science") throw new InvalidOperationException("Science requires the direct SCM service host.");
        using var writerImage = OperatingSystem.IsWindows() ? OpenWriterImage() : null;
        if (!OperatingSystem.IsWindows() && options.Qualification && options.Role == "writer")
            throw new PlatformNotSupportedException("SCM Writer requires Windows.");
        _writerImage = writerImage;
        if (options.Qualification && options.Role == "writer")
            await ValidateQualificationAsync(stoppingToken);
        logger.LogInformation(
            "{DisplayName} started in {Role} role without an interactive desktop dependency.",
            options.DisplayName,
            options.Role);
        var restartCount = 0;
        if (options.Qualification && options.Role != "writer")
            await ValidateQualificationAsync(stoppingToken);
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                using var generation = options.Qualification ? new HostProcessGeneration(options.ConfigPath, options.Role) : null;
                _generation = generation;
                await RunChildOnceAsync(stoppingToken);
                if (options.Qualification)
                {
                    lifetime.StopApplication();
                    return;
                }
                restartCount = 0;
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception exception)
            {
                logger.LogError(exception, "Continuous {Role} process failed.", options.Role);
                if (options.Qualification)
                {
                    Environment.ExitCode = 2;
                    lifetime.StopApplication();
                    return;
                }
                restartCount = Math.Min(restartCount + 1, RestartDelays.Length);
            }

            if (!stoppingToken.IsCancellationRequested)
            {
                var delay = RestartDelays[Math.Max(0, restartCount - 1)];
                logger.LogWarning(
                    "Continuous {Role} process exited; restarting after {Delay}.",
                    options.Role,
                    delay);
                await Task.Delay(delay, stoppingToken);
            }
        }
    }

    private async Task RunChildOnceAsync(CancellationToken stoppingToken)
    {
        var info = new ProcessStartInfo
        {
            FileName = options.PythonExecutable,
            WorkingDirectory = options.RepositoryRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
        };
        if (Path.GetFileNameWithoutExtension(options.PythonExecutable)
            .Equals("py", StringComparison.OrdinalIgnoreCase))
        {
            info.ArgumentList.Add("-3");
        }
        info.ArgumentList.Add("-B");
        info.ArgumentList.Add("-m");
        info.ArgumentList.Add("momentum_hunter.continuous_production");
        info.ArgumentList.Add("--role");
        info.ArgumentList.Add(options.Role);
        info.ArgumentList.Add("--config");
        info.ArgumentList.Add(options.ConfigPath);
        info.ArgumentList.Add("--host-control-stdin");
        if (_generation is not null)
        {
            info.ArgumentList.Add("--host-generation");
            info.ArgumentList.Add(_generation.Generation);
        }
        info.Environment["PYTHONUTF8"] = "1";
        info.Environment["MOMENTUM_HUNTER_CONTINUOUS_SERVICE_MODE"] = "1";
        info.Environment.Remove("OPENAI_API_KEY");
        info.Environment.Remove("CODEX_API_KEY");
        info.Environment.Remove("ALPACA_API_KEY");
        info.Environment.Remove("ALPACA_SECRET_KEY");
        if (OperatingSystem.IsWindows() && _writerImage is not null) BindWriterInterpreter(info);
        if (options.Qualification)
        {
            foreach (var key in info.Environment.Keys.ToArray())
                if (System.Text.RegularExpressions.Regex.IsMatch(key,
                    "SCHWAB|FINVIZ|ALPACA|IBKR|MH_CANARY|API_KEY|API_SECRET|OAUTH|ACCESS_TOKEN|REFRESH_TOKEN",
                    System.Text.RegularExpressions.RegexOptions.IgnoreCase))
                    info.Environment.Remove(key);
        }

        try
        {
            _process = new Process { StartInfo = info, EnableRaisingEvents = true };
            if (!_process.Start()) throw new InvalidOperationException("Continuous child failed to start.");
            var output = _process.StandardOutput;
            var error = _process.StandardError;
            _generation?.Started(_process);
            var stdout = DrainAsync(output, line => logger.LogInformation("Continuous: {Line}", line), CancellationToken.None);
            var stderr = DrainAsync(error, line => logger.LogWarning("Continuous: {Line}", line), CancellationToken.None);
            try
            {
                await WaitChildAsync(stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                await StopChildGracefullyAsync();
            }
            await Task.WhenAll(stdout, stderr);
            _lastExitCode = _process.ExitCode;
            _generation?.Exited(_lastExitCode);
            if (_lastExitCode != 0)
                throw new InvalidOperationException($"Continuous Python process exited {_lastExitCode}.");
        }
        finally
        {
            _process?.Dispose();
            _process = null;
        }
    }

    private Task WaitChildAsync(CancellationToken token = default) => _process!.WaitForExitAsync(token);

    private async Task ValidateQualificationAsync(CancellationToken token)
    {
        var info = new ProcessStartInfo(options.PythonExecutable)
        {
            WorkingDirectory = options.RepositoryRoot, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
        };
        foreach (var argument in new[] { "-B", "-m", "momentum_hunter.continuous_production", "--config", options.ConfigPath,
            options.Role == "writer" ? "--verify-writer-launch-profile" : "--print-install-plan" })
            info.ArgumentList.Add(argument);
        if (OperatingSystem.IsWindows() && _writerImage is not null) BindWriterInterpreter(info);
        foreach (var key in info.Environment.Keys.ToArray())
                if (System.Text.RegularExpressions.Regex.IsMatch(key,
                    "SCHWAB|FINVIZ|ALPACA|IBKR|MH_CANARY|API_KEY|API_SECRET|OAUTH|ACCESS_TOKEN|REFRESH_TOKEN",
                    System.Text.RegularExpressions.RegexOptions.IgnoreCase))
                    info.Environment.Remove(key);
        using var descriptor = JsonDocument.Parse(File.ReadAllBytes(options.ConfigPath));
        var evidence = Path.Combine(descriptor.RootElement.GetProperty("logRoot").GetString()!,
            options.Role, "validator-" + Guid.NewGuid().ToString("N"));
        var writerProtocol = options.Role == "writer" ? new WriterValidationProtocol(descriptor.RootElement) : null;
        var result = await QualificationValidator.RunAsync(info, evidence, TimeSpan.FromSeconds(30), token,
            writerProtocol: writerProtocol, diagnosticOnly: true);
        if (!result.Accepted)
            throw new InvalidOperationException("Read-only host configuration validation failed; durable evidence: " + evidence);
    }

    public override async Task StopAsync(CancellationToken cancellationToken)
    {
        await base.StopAsync(cancellationToken);
    }

    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    private DirectScienceImage? OpenWriterImage()
    {
        if (!options.Qualification || options.Role != "writer") return null;
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("SCM Writer requires Windows.");
        var config = System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllBytes(options.ConfigPath))!.AsObject();
        var image = new DirectScienceImage(options, config);
        try
        {
            var actor = config["host"]!["science"]!["custodyPolicy"]!["actor_profile"]!["writer"]!;
            if (!Path.GetFullPath(options.PythonExecutable).Equals(image.Resolve("python-base/python.exe"), StringComparison.OrdinalIgnoreCase) ||
                !Path.GetFullPath(options.PythonExecutable).Equals(actor["python_path"]!.GetValue<string>(), StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Writer requires the pinned direct interpreter, not a venv redirector.");
            return image;
        }
        catch { image.Dispose(); throw; }
    }

    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    private void BindWriterInterpreter(ProcessStartInfo info)
    {
        // The Windows venv redirector is a second process. Direct base CPython
        // keeps the real Writer PID bound to its existing SCM host generation.
        var arguments = info.ArgumentList.ToArray();
        if (arguments.Length < 3 || arguments[0] != "-B" || arguments[1] != "-m" ||
            arguments[2] != "momentum_hunter.continuous_production")
            throw new InvalidDataException("Writer launch arguments changed.");
        var paths = _writerImage!.Manifest["pythonPaths"]!.AsArray()
            .Select(p => _writerImage.Resolve(p!.GetValue<string>())).ToArray();
        var encoded = JsonSerializer.Serialize(JsonSerializer.Serialize(paths));
        var code = "import sys,json;sys.path[:]=json.loads(" + encoded +
            ");from momentum_hunter.continuous_production import main;raise SystemExit(main())";
        info.ArgumentList.Clear();
        foreach (var item in new[] { "-I", "-S", "-B", "-X", "utf8", "-c", code }) info.ArgumentList.Add(item);
        foreach (var item in arguments.Skip(3)) info.ArgumentList.Add(item);
    }

    private async Task StopChildGracefullyAsync()
    {
        var child = _process;
        if (child is null || child.HasExited) return;
        try
        {
            _generation?.StopRequested();
            var input = child.StandardInput;
            await input.WriteLineAsync("STOP");
            await input.FlushAsync();
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(options.ShutdownSeconds + 5));
            await WaitChildAsync(deadline.Token);
            logger.LogInformation("Continuous {Role} cooperative shutdown exited {Code}.", options.Role, child.ExitCode);
        }
        catch (Exception exception) when (exception is OperationCanceledException or IOException or InvalidOperationException)
        {
            logger.LogError(exception, "Continuous {Role} drain UNPROVEN; terminating only its owned child tree.", options.Role);
            StopChildTree();
            await WaitChildAsync();
        }
    }

    private void StopChildTree()
    {
        try
        {
            if (_process is { HasExited: false })
            {
                _process.Kill(entireProcessTree: true);
            }
        }
        catch (InvalidOperationException)
        {
            // The child exited between the state check and the stop request.
        }
    }

    private static async Task DrainAsync(
        StreamReader reader,
        Action<string> sink,
        CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            var line = await reader.ReadLineAsync(cancellationToken);
            if (line is null)
            {
                return;
            }
            sink(line);
        }
    }
}
