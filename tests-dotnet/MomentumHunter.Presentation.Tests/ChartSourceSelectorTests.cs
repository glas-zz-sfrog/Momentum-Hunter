namespace MomentumHunter.Presentation.Tests;

public sealed class ChartSourceSelectorTests
{
    [Fact]
    public void PrimaryChartHostsCompactExplicitSourceSelector()
    {
        var root = FindRepositoryRoot();
        var xaml = File.ReadAllText(
            Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "MainWindow.xaml"));
        var chartStart = xaml.IndexOf(
            "x:Name=\"PrimaryChartDocument\"",
            StringComparison.Ordinal);
        var chartEnd = xaml.IndexOf(
            "</avalon:LayoutDocument>",
            chartStart,
            StringComparison.Ordinal);
        Assert.True(chartStart >= 0);
        Assert.True(chartEnd > chartStart);
        var chart = xaml[chartStart..chartEnd];

        Assert.Contains("Content=\"Stored\"", chart, StringComparison.Ordinal);
        Assert.Contains("Content=\"Staged preview\"", chart, StringComparison.Ordinal);
        Assert.Contains("UseStoredChartSourceCommand", chart, StringComparison.Ordinal);
        Assert.Contains("UseStagedChartPreviewCommand", chart, StringComparison.Ordinal);
        Assert.Contains("IsStoredChartSource, Mode=OneWay", chart, StringComparison.Ordinal);
        Assert.Contains("IsStagedChartPreview, Mode=OneWay", chart, StringComparison.Ordinal);
        Assert.Contains("IsEnabled=\"{Binding CanUseStagedChartPreview}\"", chart, StringComparison.Ordinal);
        Assert.Contains("Text=\"{Binding ChartFooterLabel}\"", chart, StringComparison.Ordinal);
        Assert.Contains("ToolTip=\"{Binding ChartFooterLabel}\"", chart, StringComparison.Ordinal);
        Assert.Contains("MinWidth=\"52\"", chart, StringComparison.Ordinal);
        Assert.Contains("MinWidth=\"88\"", chart, StringComparison.Ordinal);
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
