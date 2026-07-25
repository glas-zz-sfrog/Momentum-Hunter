using System.Buffers.Binary;
using System.Xml.Linq;

namespace MomentumHunter.Layout.Tests;

public sealed class ApplicationIconTests
{
    [Fact]
    public void DesktopProjectEmbedsMultiResolutionMomentumHunterIcon()
    {
        var root = FindRepositoryRoot();
        var projectPath = Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "MomentumHunter.Desktop.Wpf.csproj");
        var iconPath = Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "Assets", "MomentumHunter.ico");
        var previewPath = Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "Assets", "MomentumHunterIcon.png");
        var generatorPath = Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "Assets", "generate_momentum_hunter_icon.py");
        var windowPath = Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "MainWindow.xaml");

        var project = XDocument.Load(projectPath);
        var applicationIcon = project.Descendants("ApplicationIcon").Single().Value;
        var resource = project.Descendants("Resource").Single(element =>
            string.Equals((string?)element.Attribute("Include"), @"Assets\MomentumHunter.ico", StringComparison.OrdinalIgnoreCase));

        Assert.Equal(@"Assets\MomentumHunter.ico", applicationIcon);
        Assert.NotNull(resource);
        Assert.True(File.Exists(iconPath));
        Assert.True(File.Exists(previewPath));
        Assert.True(File.Exists(generatorPath));
        Assert.Contains("Icon=\"Assets/MomentumHunter.ico\"", File.ReadAllText(windowPath), StringComparison.Ordinal);

        AssertPngDimensions(previewPath, 1024, 1024);
        var frames = ReadIconFrames(iconPath);
        Assert.Equal(
            [16, 20, 24, 32, 40, 48, 64, 128, 256],
            frames.Select(frame => frame.Width).ToArray());
        Assert.All(
            frames,
            frame =>
            {
                Assert.Equal(frame.Width, frame.Height);
                Assert.True(frame.ImageLength > PngSignature.Length);
                Assert.True(frame.IsPng);
            });
    }

    private static IconFrame[] ReadIconFrames(string iconPath)
    {
        using var stream = File.OpenRead(iconPath);
        using var reader = new BinaryReader(stream);

        Assert.Equal(0, reader.ReadUInt16());
        Assert.Equal(1, reader.ReadUInt16());
        var count = reader.ReadUInt16();
        var frames = new IconFrame[count];

        for (var index = 0; index < count; index++)
        {
            var width = reader.ReadByte();
            var height = reader.ReadByte();
            stream.Seek(6, SeekOrigin.Current);
            var imageLength = reader.ReadUInt32();
            var imageOffset = reader.ReadUInt32();

            var nextEntryPosition = stream.Position;
            stream.Position = imageOffset;
            var signature = reader.ReadBytes(PngSignature.Length);
            stream.Position = nextEntryPosition;

            frames[index] = new IconFrame(
                width == 0 ? 256 : width,
                height == 0 ? 256 : height,
                imageLength,
                signature.SequenceEqual(PngSignature));
        }

        return frames;
    }

    private static void AssertPngDimensions(string pngPath, int expectedWidth, int expectedHeight)
    {
        var bytes = File.ReadAllBytes(pngPath);

        Assert.True(bytes.AsSpan(0, PngSignature.Length).SequenceEqual(PngSignature));
        Assert.Equal("IHDR", System.Text.Encoding.ASCII.GetString(bytes, 12, 4));
        Assert.Equal(expectedWidth, BinaryPrimitives.ReadInt32BigEndian(bytes.AsSpan(16, 4)));
        Assert.Equal(expectedHeight, BinaryPrimitives.ReadInt32BigEndian(bytes.AsSpan(20, 4)));
        Assert.Equal(8, bytes[24]);
        Assert.Equal(6, bytes[25]);
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

    private static readonly byte[] PngSignature = [137, 80, 78, 71, 13, 10, 26, 10];

    private sealed record IconFrame(int Width, int Height, uint ImageLength, bool IsPng);
}
