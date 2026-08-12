using System.Collections;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed partial class XamlBindingContractTests
{
    [Fact]
    public void ProductionMainWindowBindingsResolveAgainstTheirViewModels()
    {
        var root = FindRepositoryRoot();
        var path = Path.Combine(
            root,
            "src",
            "MomentumHunter.Desktop.Wpf",
            "MainWindow.xaml");
        var document = XDocument.Load(
            path,
            LoadOptions.PreserveWhitespace | LoadOptions.SetLineInfo);
        var failures = new List<string>();

        Visit(
            document.Root ?? throw new InvalidDataException("MainWindow.xaml has no root."),
            typeof(ShellViewModel),
            templateItemTypeHint: null,
            failures);

        Assert.True(
            failures.Count == 0,
            "Production XAML contains unresolved binding paths:\n"
            + string.Join("\n", failures));
    }

    [Fact]
    public void BindingResolverRejectsRenamedRootAndNestedProperties()
    {
        Assert.False(TryResolvePath(typeof(ShellViewModel), "Candidatez", out _, out _));
        Assert.False(
            TryResolvePath(
                typeof(ShellViewModel),
                "PrimaryChart.ProviderStatusTypo",
                out _,
                out _));
    }

    [Fact]
    public void ProgrammaticBindingsUseCompileTimePropertyNames()
    {
        var root = FindRepositoryRoot();
        var sourceFiles = Directory.EnumerateFiles(
            Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf"),
            "*.cs",
            SearchOption.AllDirectories);
        var violations = sourceFiles
            .SelectMany(path => File.ReadLines(path)
                .Select((line, index) => new { path, line, number = index + 1 }))
            .Where(item => LiteralBindingPath().IsMatch(item.line))
            .Select(item => $"{item.path}:{item.number}: {item.line.Trim()}")
            .ToArray();

        Assert.True(
            violations.Length == 0,
            "Programmatic WPF bindings must use nameof(...) so property renames fail compilation:\n"
            + string.Join("\n", violations));
    }

    private static void Visit(
        XElement element,
        Type currentType,
        Type? templateItemTypeHint,
        ICollection<string> failures)
    {
        ValidateElementBindings(element, currentType, failures);

        var effectiveType = ResolveDataContextOverride(element, currentType) ?? currentType;
        var itemType = ResolveBoundPropertyType(element, "ItemsSource", effectiveType);
        itemType = itemType is null ? null : CollectionItemType(itemType);
        var contentType = ResolveBoundPropertyType(element, "Content", effectiveType);

        foreach (var child in element.Elements())
        {
            var localName = child.Name.LocalName;
            if (localName.EndsWith(".ItemTemplate", StringComparison.Ordinal))
            {
                Visit(child, effectiveType, itemType, failures);
                continue;
            }
            if (localName.EndsWith(".Columns", StringComparison.Ordinal))
            {
                Visit(child, itemType ?? effectiveType, itemType, failures);
                continue;
            }
            if (localName.EndsWith(".ContentTemplate", StringComparison.Ordinal))
            {
                Visit(child, effectiveType, contentType, failures);
                continue;
            }
            if (localName == "DataTemplate" && templateItemTypeHint is not null)
            {
                Visit(child, templateItemTypeHint, templateItemTypeHint, failures);
                continue;
            }

            Visit(child, effectiveType, templateItemTypeHint, failures);
        }
    }

    private static void ValidateElementBindings(
        XElement element,
        Type currentType,
        ICollection<string> failures)
    {
        foreach (var attribute in element.Attributes())
        {
            var raw = attribute.Value.Trim();
            if (!raw.StartsWith("{Binding", StringComparison.Ordinal)
                || IsNonDataContextBinding(raw))
            {
                continue;
            }

            var path = BindingPath(raw);
            ValidatePath(element, currentType, path, failures);
        }

        if (element.Name.LocalName != "Binding"
            || element.Attribute("Path") is not { } pathAttribute
            || element.Attribute("RelativeSource") is not null
            || element.Elements().Any(child => child.Name.LocalName == "Binding.RelativeSource"))
        {
            return;
        }

        ValidatePath(element, currentType, pathAttribute.Value.Trim(), failures);
    }

    private static void ValidatePath(
        XElement element,
        Type currentType,
        string path,
        ICollection<string> failures)
    {
        if (string.IsNullOrWhiteSpace(path)
            || path == "."
            || path.StartsWith("(", StringComparison.Ordinal)
            || path.Contains("/", StringComparison.Ordinal))
        {
            return;
        }

        if (!TryResolvePath(currentType, path, out _, out var failedSegment))
        {
            var line = ((IXmlLineInfo)element).HasLineInfo()
                ? ((IXmlLineInfo)element).LineNumber
                : 0;
            failures.Add(
                $"line {line}: {currentType.Name}.{path} "
                + $"(missing '{failedSegment}')");
        }
    }

    private static Type? ResolveDataContextOverride(XElement element, Type currentType)
    {
        var raw = element.Attribute("DataContext")?.Value.Trim();
        if (string.IsNullOrWhiteSpace(raw)
            || !raw.StartsWith("{Binding", StringComparison.Ordinal)
            || IsNonDataContextBinding(raw))
        {
            return null;
        }

        var path = BindingPath(raw);
        return TryResolvePath(currentType, path, out var resolved, out _)
            ? resolved
            : null;
    }

    private static Type? ResolveBoundPropertyType(
        XElement element,
        string attributeName,
        Type currentType)
    {
        var raw = element.Attribute(attributeName)?.Value.Trim();
        if (string.IsNullOrWhiteSpace(raw)
            || !raw.StartsWith("{Binding", StringComparison.Ordinal)
            || IsNonDataContextBinding(raw))
        {
            return null;
        }

        var path = BindingPath(raw);
        return TryResolvePath(currentType, path, out var resolved, out _)
            ? resolved
            : null;
    }

    private static bool TryResolvePath(
        Type sourceType,
        string path,
        out Type resolvedType,
        out string failedSegment)
    {
        resolvedType = sourceType;
        failedSegment = string.Empty;
        foreach (var segment in path.Split('.'))
        {
            var normalized = IndexerSuffix().Replace(segment.Trim(), string.Empty);
            if (normalized.Length == 0)
            {
                continue;
            }

            var property = UnwrapNullable(resolvedType).GetProperty(
                normalized,
                BindingFlags.Instance | BindingFlags.Public);
            if (property is null)
            {
                failedSegment = normalized;
                return false;
            }

            resolvedType = property.PropertyType;
        }

        return true;
    }

    private static Type UnwrapNullable(Type type) => Nullable.GetUnderlyingType(type) ?? type;

    private static Type? CollectionItemType(Type type)
    {
        type = UnwrapNullable(type);
        if (type.IsArray)
        {
            return type.GetElementType();
        }
        if (type.IsGenericType && type.GetGenericTypeDefinition() == typeof(IEnumerable<>))
        {
            return type.GetGenericArguments()[0];
        }

        return type.GetInterfaces()
            .FirstOrDefault(candidate => candidate.IsGenericType
                && candidate.GetGenericTypeDefinition() == typeof(IEnumerable<>))
            ?.GetGenericArguments()[0];
    }

    private static bool IsNonDataContextBinding(string raw) =>
        raw.Contains("RelativeSource", StringComparison.Ordinal)
        || raw.Contains("ElementName=", StringComparison.Ordinal)
        || raw.StartsWith("{Binding Source=", StringComparison.Ordinal);

    private static string BindingPath(string raw)
    {
        var match = BindingMarkup().Match(raw);
        if (!match.Success)
        {
            return string.Empty;
        }

        var path = match.Groups[1].Value.Trim();
        return path.StartsWith("Path=", StringComparison.Ordinal)
            ? path[5..].Trim()
            : path;
    }

    private static string FindRepositoryRoot()
    {
        for (var current = new DirectoryInfo(AppContext.BaseDirectory);
             current is not null;
             current = current.Parent)
        {
            if (File.Exists(Path.Combine(current.FullName, "AGENTS.md"))
                && File.Exists(Path.Combine(
                    current.FullName,
                    "src",
                    "MomentumHunter.Desktop.Wpf",
                    "MainWindow.xaml")))
            {
                return current.FullName;
            }
        }

        throw new DirectoryNotFoundException("Repository root was not found.");
    }

    [GeneratedRegex(@"^\{Binding(?:\s+([^,}]+))?")]
    private static partial Regex BindingMarkup();

    [GeneratedRegex(@"\[.*\]$")]
    private static partial Regex IndexerSuffix();

    [GeneratedRegex("new\\s+Binding\\s*\\(\\s*\\\"")]
    private static partial Regex LiteralBindingPath();
}
