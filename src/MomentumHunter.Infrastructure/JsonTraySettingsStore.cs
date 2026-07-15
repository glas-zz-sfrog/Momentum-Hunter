using System.Text.Json;
using MomentumHunter.Application;

namespace MomentumHunter.Infrastructure;

public sealed class JsonTraySettingsStore : ITraySettingsStore
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };

    private readonly string _path;

    public JsonTraySettingsStore(string path)
    {
        _path = path;
    }

    public async Task<TraySettings> LoadAsync(CancellationToken cancellationToken = default)
    {
        if (!File.Exists(_path))
        {
            return new TraySettings();
        }

        try
        {
            await using var stream = File.OpenRead(_path);
            return await JsonSerializer.DeserializeAsync<TraySettings>(stream, SerializerOptions, cancellationToken) ?? new TraySettings();
        }
        catch (JsonException)
        {
            return new TraySettings();
        }
        catch (IOException)
        {
            return new TraySettings();
        }
        catch (UnauthorizedAccessException)
        {
            return new TraySettings();
        }
    }

    public async Task SaveAsync(TraySettings settings, CancellationToken cancellationToken = default)
    {
        var directory = Path.GetDirectoryName(_path);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }

        var temporaryPath = $"{_path}.tmp";
        await using (var stream = File.Create(temporaryPath))
        {
            await JsonSerializer.SerializeAsync(stream, settings, SerializerOptions, cancellationToken);
        }

        File.Move(temporaryPath, _path, overwrite: true);
    }
}
