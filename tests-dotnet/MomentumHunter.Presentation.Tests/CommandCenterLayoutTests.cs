using System.Xml.Linq;

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

    [Fact]
    public void RankedBoardDisablesHorizontalScrollingAndKeepsHeaderRowColumnParity()
    {
        var root = FindRepositoryRoot();
        var path = Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "Controls", "CommandCenterView.xaml");
        var document = XDocument.Load(path);
        XNamespace presentation = "http://schemas.microsoft.com/winfx/2006/xaml/presentation";
        var rankedList = document
            .Descendants(presentation + "ListBox")
            .Single(item => (string?)item.Attribute("ItemsSource") == "{Binding CommandCenterRankedCandidates}");

        Assert.Equal("Disabled", (string?)rankedList.Attribute("ScrollViewer.HorizontalScrollBarVisibility"));

        var catalystHeader = document
            .Descendants(presentation + "TextBlock")
            .Single(item => (string?)item.Attribute("Text") == "CATALYST / POPULATION");
        var headerGrid = Assert.IsType<XElement>(catalystHeader.Parent);
        var catalystRow = rankedList
            .Descendants(presentation + "TextBlock")
            .Single(item => (string?)item.Attribute("Text") == "{Binding CatalystSummary}");
        var rowGrid = catalystRow
            .Ancestors(presentation + "Grid")
            .First(item => item.Element(presentation + "Grid.ColumnDefinitions") is not null);
        var expectedWidths = new[] { "34", "70", "64", "58", "1*", "142", "76" };

        Assert.Equal(expectedWidths, ColumnWidths(headerGrid, presentation));
        Assert.Equal(expectedWidths, ColumnWidths(rowGrid, presentation));
        Assert.Equal("CharacterEllipsis", (string?)catalystRow.Attribute("TextTrimming"));
        Assert.Equal("4", (string?)catalystRow.Parent?.Attribute("Grid.Column"));
        Assert.Contains(
            rankedList.Descendants(),
            item => item.Name.LocalName == "MicroChartControl"
                && (string?)item.Attribute("Grid.Column") == "5"
                && (string?)item.Attribute("Series") == "{Binding DisplayMiniChart}");
        Assert.Contains(
            rankedList.Descendants(presentation + "TextBlock"),
            item => (string?)item.Attribute("Text") == "{Binding DisplayFreshness.DisplayFreshnessLabel}"
                && (string?)item.Parent?.Attribute("Grid.Column") == "6");
    }

    private static string[] ColumnWidths(XElement grid, XNamespace presentation) => grid
        .Element(presentation + "Grid.ColumnDefinitions")!
        .Elements(presentation + "ColumnDefinition")
        .Select(item => (string?)item.Attribute("Width") ?? string.Empty)
        .ToArray();

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
