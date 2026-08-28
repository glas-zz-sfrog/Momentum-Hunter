namespace MomentumHunter.Presentation.Tests;

public sealed class CommandCenterLayoutTests
{
    [Fact]
    public void CommandCenterIsTheDefaultAndLegacyDockLayoutIsRetiredFromDefaultView()
    {
        var root = FindRepositoryRoot();
        var main = File.ReadAllText(Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "MainWindow.xaml"));
        var commandCenter = File.ReadAllText(Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "Controls", "CommandCenterView.xaml"));

        Assert.Contains("<controls:CommandCenterView Grid.Row=\"1\"", main, StringComparison.Ordinal);
        Assert.Contains("x:Name=\"DockManager\"", main, StringComparison.Ordinal);
        Assert.Contains("Visibility=\"Collapsed\"", main, StringComparison.Ordinal);
        Assert.Contains("CROSS-LIFECYCLE RANKED CANDIDATES", commandCenter, StringComparison.Ordinal);
        Assert.Contains("RADAR MAP GEOMETRY NOT YET AUTHORIZED", ReadViewModelSource(root), StringComparison.Ordinal);
        Assert.Contains("ItemsSource=\"{Binding CommandCenterAccepted}\"", commandCenter, StringComparison.Ordinal);
        Assert.Contains("ItemsSource=\"{Binding CommandCenterRejected}\"", commandCenter, StringComparison.Ordinal);
        Assert.Contains("Series=\"{Binding DisplayMiniChart}\"", commandCenter, StringComparison.Ordinal);
        Assert.Contains("FAKEBROKER · READ ONLY", commandCenter, StringComparison.Ordinal);
        Assert.Contains("READ MODEL · NOT HOST HEALTH", commandCenter, StringComparison.Ordinal);
        Assert.Contains("CommandCenterHostHealthLabel", main, StringComparison.Ordinal);
        Assert.Contains("TextTrimming=\"CharacterEllipsis\"", main, StringComparison.Ordinal);
        Assert.DoesNotContain("Buy", commandCenter, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("Sell", commandCenter, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("Submit", commandCenter, StringComparison.OrdinalIgnoreCase);
    }

    private static string ReadViewModelSource(string root) => File.ReadAllText(
        Path.Combine(root, "src", "MomentumHunter.Presentation", "ShellViewModel.cs"));

    private static string FindRepositoryRoot()
    {
        for (var current = new DirectoryInfo(AppContext.BaseDirectory); current is not null; current = current.Parent)
        {
            if (File.Exists(Path.Combine(current.FullName, "AGENTS.md")))
            {
                return current.FullName;
            }
        }
        throw new DirectoryNotFoundException("Repository root was not found.");
    }
}
