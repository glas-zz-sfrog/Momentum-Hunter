using Microsoft.Extensions.Logging.Abstractions;
using MomentumHunter.AutomationService;

namespace MomentumHunter.Integration.Tests;

public sealed class AutomationServiceTests
{
    [Fact]
    public void StartInfoLaunchesHeadlessSupervisorWithoutApiKeyInheritance()
    {
        var options = new PythonAutomationSupervisorOptions(
            @"C:\MomentumHunter",
            @"C:\Python\python.exe",
            @"C:\ProgramData\MomentumHunter\Automation\automation-manifest.json",
            TimeSpan.FromSeconds(5));
        var worker = new PythonAutomationSupervisorWorker(
            options,
            NullLogger<PythonAutomationSupervisorWorker>.Instance);

        var startInfo = worker.BuildStartInfo();

        Assert.False(startInfo.UseShellExecute);
        Assert.True(startInfo.CreateNoWindow);
        Assert.Equal(@"C:\MomentumHunter", startInfo.WorkingDirectory);
        Assert.Equal(@"C:\Python\python.exe", startInfo.FileName);
        Assert.Equal(
            new[]
            {
                "-B",
                "-m",
                "momentum_hunter.automation_supervisor",
                "run",
                "--manifest",
                @"C:\ProgramData\MomentumHunter\Automation\automation-manifest.json",
            },
            startInfo.ArgumentList);
        Assert.Equal("1", startInfo.Environment["MOMENTUM_HUNTER_SERVICE_MODE"]);
        Assert.False(startInfo.Environment.ContainsKey("OPENAI_API_KEY"));
        Assert.False(startInfo.Environment.ContainsKey("CODEX_API_KEY"));
    }

    [Fact]
    public void ServiceIdentityIsStableAndProductSpecific()
    {
        Assert.Equal("MomentumHunterAutomation", ServiceIdentity.ServiceName);
        Assert.Equal(
            "Momentum Hunter Automation Service",
            ServiceIdentity.DisplayName);
    }

    [Fact]
    public void ServiceArgumentsPinRepositoryPythonAndManifest()
    {
        var options = PythonAutomationSupervisorOptions.Create(
            new[]
            {
                "--repository-root",
                @"C:\Pinned\MomentumHunter",
                "--python-executable",
                @"C:\Pinned\python.exe",
                "--manifest",
                @"C:\ProgramData\MomentumHunter\Automation\manifest.json",
            });

        Assert.Equal(@"C:\Pinned\MomentumHunter", options.RepositoryRoot);
        Assert.Equal(@"C:\Pinned\python.exe", options.PythonExecutable);
        Assert.Equal(
            @"C:\ProgramData\MomentumHunter\Automation\manifest.json",
            options.ManifestPath);
    }

    [Fact]
    public void ServiceArgumentsRejectUnknownOrDuplicateValues()
    {
        Assert.Throws<ArgumentException>(
            () => PythonAutomationSupervisorOptions.Create(
                new[] { "--interactive", "true" }));
        Assert.Throws<ArgumentException>(
            () => PythonAutomationSupervisorOptions.Create(
                new[]
                {
                    "--manifest",
                    @"C:\one.json",
                    "--manifest",
                    @"C:\two.json",
                }));
    }
}
