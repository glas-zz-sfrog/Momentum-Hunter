using System.Diagnostics;

namespace MomentumHunter.ContinuousServiceHost;

public sealed record ContinuousServiceOptions(
    string Role,
    string RepositoryRoot,
    string PythonExecutable,
    string ConfigPath,
    string ServiceName,
    string DisplayName)
{
    public static ContinuousServiceOptions Create(IReadOnlyList<string> args)
    {
        var values = Parse(args);
        var role = values.GetValueOrDefault("--role")
            ?? throw new ArgumentException("--role is required.");
        if (role is not ("writer" or "runtime" or "paper"))
        {
            throw new ArgumentException("--role must be writer, runtime, or paper.");
        }

        var repositoryRoot = Required(values, "--repository-root");
        var pythonExecutable = Required(values, "--python-executable");
        var configPath = Required(values, "--config");
        var suffix = role switch
        {
            "writer" => "Writer",
            "runtime" => "Runtime",
            _ => "Paper",
        };
        var displayName = role.Equals("paper", StringComparison.Ordinal)
            ? "Momentum Hunter Continuous Paper (One-Entry Canary)"
            : $"Momentum Hunter Continuous {suffix} (Research Only)";
        return new ContinuousServiceOptions(
            role,
            Path.GetFullPath(repositoryRoot),
            pythonExecutable,
            Path.GetFullPath(configPath),
            $"MomentumHunterContinuous{suffix}",
            displayName);
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
            "--role", "--repository-root", "--python-executable", "--config"
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
    ILogger<ContinuousProcessWorker> logger)
    : BackgroundService
{
    private Process? _process;
    private static readonly TimeSpan[] RestartDelays =
    {
        TimeSpan.FromSeconds(5),
        TimeSpan.FromSeconds(15),
        TimeSpan.FromSeconds(60),
    };

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        logger.LogInformation(
            "{DisplayName} started in {Role} role without an interactive desktop dependency.",
            options.DisplayName,
            options.Role);
        var restartCount = 0;
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await RunChildOnceAsync(stoppingToken);
                restartCount = 0;
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception exception)
            {
                logger.LogError(exception, "Continuous {Role} process failed.", options.Role);
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
        };
        if (Path.GetFileNameWithoutExtension(options.PythonExecutable)
            .Equals("py", StringComparison.OrdinalIgnoreCase))
        {
            info.ArgumentList.Add("-3");
        }
        info.ArgumentList.Add("-B");
        info.ArgumentList.Add("-m");
        if (options.Role.Equals("paper", StringComparison.Ordinal))
        {
            info.ArgumentList.Add("momentum_hunter.continuous_paper");
            info.ArgumentList.Add("--config");
            info.ArgumentList.Add(options.ConfigPath);
            info.ArgumentList.Add("run");
        }
        else
        {
            info.ArgumentList.Add("momentum_hunter.continuous_production");
            info.ArgumentList.Add("--role");
            info.ArgumentList.Add(options.Role);
            info.ArgumentList.Add("--config");
            info.ArgumentList.Add(options.ConfigPath);
        }
        info.Environment["PYTHONUTF8"] = "1";
        info.Environment["MOMENTUM_HUNTER_CONTINUOUS_SERVICE_MODE"] = "1";
        info.Environment["MOMENTUM_HUNTER_CONTINUOUS_PAPER_MODE"] =
            options.Role.Equals("paper", StringComparison.Ordinal) ? "1" : "0";
        info.Environment.Remove("OPENAI_API_KEY");
        info.Environment.Remove("CODEX_API_KEY");
        info.Environment.Remove("ALPACA_API_KEY");
        info.Environment.Remove("ALPACA_SECRET_KEY");

        _process = new Process { StartInfo = info, EnableRaisingEvents = true };
        if (!_process.Start())
        {
            throw new InvalidOperationException("Continuous Python process could not be started.");
        }
        var stdout = DrainAsync(_process.StandardOutput, line => logger.LogInformation("Continuous: {Line}", line), stoppingToken);
        var stderr = DrainAsync(_process.StandardError, line => logger.LogWarning("Continuous: {Line}", line), stoppingToken);
        try
        {
            await _process.WaitForExitAsync(stoppingToken);
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
            StopChildTree();
            throw;
        }
        finally
        {
            await Task.WhenAll(stdout, stderr);
        }
        var exitCode = _process.ExitCode;
        _process.Dispose();
        _process = null;
        if (exitCode != 0)
        {
            throw new InvalidOperationException($"Continuous Python process exited with code {exitCode}.");
        }
    }

    public override async Task StopAsync(CancellationToken cancellationToken)
    {
        StopChildTree();
        await base.StopAsync(cancellationToken);
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
