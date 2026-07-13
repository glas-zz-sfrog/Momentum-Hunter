using System.Globalization;
using System.IO;
using System.Xml;
using AvalonDock;
using AvalonDock.Layout;
using AvalonDock.Layout.Serialization;

namespace MomentumHunter.Desktop.Wpf;

internal static class DockLayoutPersistence
{
    public static string Serialize(DockingManager dockingManager)
    {
        var serializer = new XmlLayoutSerializer(dockingManager);
        using var buffer = new StringWriter(CultureInfo.InvariantCulture);
        using var writer = XmlWriter.Create(buffer, new XmlWriterSettings
        {
            Indent = false,
            OmitXmlDeclaration = true,
        });
        serializer.Serialize(writer);
        writer.Flush();
        return buffer.ToString();
    }

    public static bool TryRestore(
        DockingManager dockingManager,
        string? xml,
        Func<string, object?> resolveContent)
    {
        if (string.IsNullOrWhiteSpace(xml) || !xml.TrimStart().StartsWith('<'))
        {
            return false;
        }

        try
        {
            var serializer = new XmlLayoutSerializer(dockingManager);
            serializer.LayoutSerializationCallback += (_, args) =>
            {
                if (!string.IsNullOrWhiteSpace(args.Model.ContentId))
                {
                    args.Content = resolveContent(args.Model.ContentId);
                }
            };
            using var buffer = new StringReader(xml);
            using var reader = XmlReader.Create(buffer, new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit });
            serializer.Deserialize(reader);
            return true;
        }
        catch (XmlException)
        {
            return false;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }

}
