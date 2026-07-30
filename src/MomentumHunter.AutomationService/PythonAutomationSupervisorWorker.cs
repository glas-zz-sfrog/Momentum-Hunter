using System.Diagnostics;

namespace MomentumHunter.AutomationService;

public static class ServiceIdentity
{
    public const string ServiceName = "MomentumHunterAutomation";
    public const string DisplayName = "Momentum Hunter Automation Service";
}

public sealed record PythonAutomationSupervisorOptions(
    string RepositoryRoot,
    string PythonExecutable,
    string ManifestPath,
    TimeSpan RestartDelay)
{
    public static PythonAutomationSupervisorOptions Create(
        IReadOnlyList<string> arguments)
    {
        var configured = ParseArguments(arguments);
        var defaults = CreateDefault();
        return new PythonAutomationSupervisorOptions(
            Path.GetFullPath(
                configured.GetValueOrDefault("--repository-root")
                ?? defaults.RepositoryRoot),
            configured.GetValueOrDefault("--python-executable")
                ?? defaults.PythonExecutable,
            Path.GetFullPath(
                configured.GetValueOrDefault("--manifest")
                ?? defaults.ManifestPath),
            defaults.RestartDelay);
    }

    public static PythonAutomationSupervisorOptions CreateDefault()
    {
        var repositoryRoot = Environment.GetEnvironmentVariable(
            "MOMENTUM_HUNTER_REPOSITORY_ROOT");
        if (string.IsNullOrWhiteSpace(repositoryRoot))
        {
            repositoryRoot = FindRepositoryRoot() ?? Directory.GetCurrentDirectory();
        }

        var pythonExecutable = Environment.GetEnvironmentVariable(
            "MOMENTUM_HUNTER_PYTHON_EXECUTABLE");
        if (string.IsNullOrWhiteSpace(pythonExecutable))
        {
            var repositoryPython = Path.Combine(
                repositoryRoot,
                ".venv",
                "Scripts",
                "python.exe");
            pythonExecutable = File.Exists(repositoryPython)
                ? repositoryPython
                : "py";
        }

        var manifestPath = Environment.GetEnvironmentVariable(
            "MOMENTUM_HUNTER_AUTOMATION_MANIFEST");
        if (string.IsNullOrWhiteSpace(manifestPath))
        {
            manifestPath = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                "MomentumHunter",
                "Automation",
                "automation-manifest.json");
        }

        return new PythonAutomationSupervisorOptions(
            Path.GetFullPath(repositoryRoot),
            pythonExecutable,
            Path.GetFullPath(manifestPath),
            TimeSpan.FromSeconds(5));
    }

    private static Dictionary<string, string> ParseArguments(
        IReadOnlyList<string> arguments)
    {
        var allowed = new HashSet<string>(StringComparer.Ordinal)
        {
            "--repository-root",
            "--python-executable",
            "--manifest",
        };
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        for (var index = 0; index < arguments.Count; index += 2)
        {
            var name = arguments[index];
            if (!allowed.Contains(name))
            {
                throw new ArgumentException(
                    $"Unsupported service argument: {name}");
            }
            if (index + 1 >= arguments.Count
                || string.IsNullOrWhiteSpace(arguments[index + 1]))
            {
                throw new ArgumentException(
                    $"Service argument requires a value: {name}");
            }
            if (!result.TryAdd(name, arguments[index + 1]))
            {
                throw new ArgumentException(
                    $"Service argument was provided more than once: {name}");
            }
        }
        return result;
    }

    private static string? FindRepositoryRoot()
    {
        var candidates = new[]
        {
            Directory.GetCurrentDirectory(),
            AppContext.BaseDirectory,
        };
        foreach (var candidate in candidates)
        {
            for (
                var current = new DirectoryInfo(Path.GetFullPath(candidate));
                current is not null;
                current = current.Parent)
            {
                if (File.Exists(Path.Combine(
                        current.FullName,
                        "momentum_hunter",
                        "automation_supervisor.py")))
                {
                    return current.FullName;
                }
            }
        }

        return null;
    }
}

public sealed class PythonAutomationSupervisorWorker(
    PythonAutomationSupervisorOptions options,
    ILogger<PythonAutomationSupervisorWorker> logger)
    : BackgroundService
{
    private Process? _process;

    public ProcessStartInfo BuildStartInfo()
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = options.PythonExecutable,
            WorkingDirectory = options.RepositoryRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        if (string.Equals(
                Path.GetFileNameWithoutExtension(options.PythonExecutable),
                "py",
                StringComparison.OrdinalIgnoreCase))
        {
            startInfo.ArgumentList.Add("-3");
        }
        startInfo.ArgumentList.Add("-B");
        startInfo.ArgumentList.Add("-m");
        startInfo.ArgumentList.Add("momentum_hunter.automation_supervisor");
        startInfo.ArgumentList.Add("run");
        startInfo.ArgumentList.Add("--manifest");
        startInfo.ArgumentList.Add(options.ManifestPath);
        startInfo.Environment["PYTHONUTF8"] = "1";
        startInfo.Environment["MOMENTUM_HUNTER_SERVICE_MODE"] = "1";
        startInfo.Environment.Remove("OPENAI_API_KEY");
        startInfo.Environment.Remove("CODEX_API_KEY");
        return startInfo;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        logger.LogInformation(
            "{DisplayName} started without an interactive desktop dependency.",
            ServiceIdentity.DisplayName);
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await RunSupervisorOnceAsync(stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception exception)
            {
                logger.LogError(
                    exception,
                    "Automation supervisor process failed before a normal exit.");
            }

            if (!stoppingToken.IsCancellationRequested)
            {
                logger.LogWarning(
                    "Automation supervisor exited; restarting after {Delay}.",
                    options.RestartDelay);
                await Task.Delay(options.RestartDelay, stoppingToken);
            }
        }
    }

    private async Task RunSupervisorOnceAsync(CancellationToken stoppingToken)
    {
        var startInfo = BuildStartInfo();
        _process = new Process
        {
            StartInfo = startInfo,
            EnableRaisingEvents = true,
        };
        if (!_process.Start())
        {
            throw new InvalidOperationException(
                "Python automation supervisor could not be started.");
        }

        var stdout = DrainOutputAsync(
            _process.StandardOutput,
            message => logger.LogInformation("Supervisor: {Message}", message),
            stoppingToken);
        var stderr = DrainOutputAsync(
            _process.StandardError,
            message => logger.LogWarning("Supervisor: {Message}", message),
            stoppingToken);

        try
        {
            await _process.WaitForExitAsync(stoppingToken);
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
            StopProcessTree();
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
            throw new InvalidOperationException(
                $"Python automation supervisor exited with code {exitCode}.");
        }
    }

    public override async Task StopAsync(CancellationToken cancellationToken)
    {
        StopProcessTree();
        await base.StopAsync(cancellationToken);
    }

    private void StopProcessTree()
    {
        if (_process is null)
        {
            return;
        }
        try
        {
            if (!_process.HasExited)
            {
                _process.Kill(entireProcessTree: true);
            }
        }
        catch (InvalidOperationException)
        {
            // The child exited between the state check and the stop request.
        }
    }

    private static async Task DrainOutputAsync(
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
