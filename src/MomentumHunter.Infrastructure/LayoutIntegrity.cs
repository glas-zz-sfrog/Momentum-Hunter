using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using MomentumHunter.Contracts;

namespace MomentumHunter.Infrastructure;

public static class LayoutIntegrity
{
    private static readonly JsonSerializerOptions SerializerOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = false,
    };

    public static WorkspaceLayoutSnapshot Seal(WorkspaceLayoutSnapshot snapshot)
    {
        return snapshot with { Checksum = ComputeChecksum(snapshot) };
    }

    public static bool IsValid(WorkspaceLayoutSnapshot snapshot)
    {
        return string.Equals(snapshot.Checksum, ComputeChecksum(snapshot), StringComparison.Ordinal);
    }

    public static string Serialize(WorkspaceLayoutSnapshot snapshot) => JsonSerializer.Serialize(snapshot, SerializerOptions);

    public static WorkspaceLayoutSnapshot? Deserialize(string json) => JsonSerializer.Deserialize<WorkspaceLayoutSnapshot>(json, SerializerOptions);

    private static string ComputeChecksum(WorkspaceLayoutSnapshot snapshot)
    {
        var canonical = snapshot with { Checksum = string.Empty };
        var payload = JsonSerializer.Serialize(canonical, SerializerOptions);
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(payload)));
    }
}
