namespace MomentumHunter.Presentation.Tests;

public sealed class WindowChromeTests
{
    [Fact]
    public void WorkstationUsesOneIntegratedNativeChromeSurface()
    {
        var (xaml, codeBehind) = ReadWindowSources();

        Assert.Contains("WindowStyle=\"None\"", xaml, StringComparison.Ordinal);
        Assert.Contains("ResizeMode=\"CanResize\"", xaml, StringComparison.Ordinal);
        Assert.Contains("MinWidth=\"1280\"", xaml, StringComparison.Ordinal);
        Assert.Contains("<shell:WindowChrome.WindowChrome>", xaml, StringComparison.Ordinal);
        Assert.Contains("CaptionHeight=\"72\"", xaml, StringComparison.Ordinal);
        Assert.Contains("ResizeBorderThickness=\"6\"", xaml, StringComparison.Ordinal);
        Assert.Contains("UseAeroCaptionButtons=\"False\"", xaml, StringComparison.Ordinal);
        Assert.Contains("x:Name=\"IntegratedTitleBar\"", xaml, StringComparison.Ordinal);
        Assert.Contains("SystemCommands.MinimizeWindow(this)", codeBehind, StringComparison.Ordinal);
        Assert.Contains("SystemCommands.MaximizeWindow(this)", codeBehind, StringComparison.Ordinal);
        Assert.Contains("SystemCommands.RestoreWindow(this)", codeBehind, StringComparison.Ordinal);
        Assert.Contains("SystemCommands.CloseWindow(this)", codeBehind, StringComparison.Ordinal);
        Assert.Contains("SystemCommands.ShowSystemMenu(this", codeBehind, StringComparison.Ordinal);
    }

    [Fact]
    public void CaptionControlsRemainInteractiveAndAccessible()
    {
        var (xaml, codeBehind) = ReadWindowSources();

        Assert.Contains("shell:WindowChrome.IsHitTestVisibleInChrome", xaml, StringComparison.Ordinal);
        Assert.Contains("AutomationProperties.Name=\"Minimize window\"", xaml, StringComparison.Ordinal);
        Assert.Contains("AutomationProperties.Name=\"Maximize window\"", xaml, StringComparison.Ordinal);
        Assert.Contains("AutomationProperties.Name=\"Close window\"", xaml, StringComparison.Ordinal);
        Assert.Contains("StateChanged=\"Window_StateChanged\"", xaml, StringComparison.Ordinal);
        Assert.Contains("UpdateWindowChromeState();", codeBehind, StringComparison.Ordinal);
        Assert.Contains("\"Restore window\" : \"Maximize window\"", codeBehind, StringComparison.Ordinal);
    }

    [Fact]
    public void GlobalEnvironmentBadgeOwnsDormantLiveMoneyTreatment()
    {
        var (xaml, _) = ReadWindowSources();

        Assert.Contains("x:Name=\"EnvironmentBadge\"", xaml, StringComparison.Ordinal);
        Assert.Equal(1, CountOccurrences(xaml, "Value=\"LIVE MONEY\""));
        Assert.Contains("<Setter Property=\"Background\" Value=\"#A51D22\"", xaml, StringComparison.Ordinal);
        Assert.DoesNotContain("Content=\"LIVE MONEY\"", xaml, StringComparison.Ordinal);
    }

    [Fact]
    public void WorkstationDeclaresPerMonitorV2DpiAwareness()
    {
        var root = FindRepositoryRoot();
        var project = File.ReadAllText(
            Path.Combine(
                root,
                "src",
                "MomentumHunter.Desktop.Wpf",
                "MomentumHunter.Desktop.Wpf.csproj"));
        var manifest = File.ReadAllText(
            Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "app.manifest"));

        Assert.Contains("<ApplicationManifest>app.manifest</ApplicationManifest>", project, StringComparison.Ordinal);
        Assert.Contains("<ApplicationHighDpiMode>PerMonitorV2</ApplicationHighDpiMode>", project, StringComparison.Ordinal);
        Assert.DoesNotContain("<dpiAware", manifest, StringComparison.Ordinal);
        Assert.DoesNotContain("<dpiAwareness", manifest, StringComparison.Ordinal);
        Assert.Contains("requestedExecutionLevel level=\"asInvoker\"", manifest, StringComparison.Ordinal);
    }

    private static int CountOccurrences(string value, string search)
    {
        var count = 0;
        var index = 0;
        while ((index = value.IndexOf(search, index, StringComparison.Ordinal)) >= 0)
        {
            count++;
            index += search.Length;
        }

        return count;
    }

    private static (string Xaml, string CodeBehind) ReadWindowSources()
    {
        var root = FindRepositoryRoot();
        return (
            File.ReadAllText(
                Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "MainWindow.xaml")),
            File.ReadAllText(
                Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "MainWindow.xaml.cs")));
    }

    private static string FindRepositoryRoot()
    {
        var current = new DirectoryInfo(AppContext.BaseDirectory);
        while (current is not null)
        {
            if (File.Exists(Path.Combine(current.FullName, "MomentumHunter.Workstation.sln")))
            {
                return current.FullName;
            }

            current = current.Parent;
        }

        throw new DirectoryNotFoundException("Could not locate the Momentum Hunter repository root.");
    }
}
