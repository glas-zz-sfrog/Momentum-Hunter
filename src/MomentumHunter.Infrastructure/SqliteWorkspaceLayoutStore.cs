using Microsoft.Data.Sqlite;
using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.Infrastructure;

/// <summary>
/// Stores workstation layout snapshots only. The model deliberately carries no
/// engine authorization, credentials, or market/provider configuration.
/// </summary>
public sealed class SqliteWorkspaceLayoutStore : IWorkspaceLayoutStore
{
    private readonly string _connectionString;

    public SqliteWorkspaceLayoutStore(string databasePath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(databasePath);
        var fullPath = Path.GetFullPath(databasePath);
        Directory.CreateDirectory(Path.GetDirectoryName(fullPath)!);
        _connectionString = new SqliteConnectionStringBuilder { DataSource = fullPath }.ToString();
    }

    public async Task SaveAsync(WorkspaceLayoutSnapshot snapshot, CancellationToken cancellationToken = default)
    {
        var sealedSnapshot = LayoutIntegrity.Seal(snapshot);
        await using var connection = await OpenAsync(cancellationToken);
        await using var transaction = (SqliteTransaction)await connection.BeginTransactionAsync(cancellationToken);

        await using (var command = connection.CreateCommand())
        {
            command.Transaction = transaction;
            command.CommandText = """
                INSERT OR REPLACE INTO workstation_layout_snapshots
                    (revision_id, workspace, created_at, is_named_layout, layout_name, payload_json)
                VALUES ($revisionId, $workspace, $createdAt, $isNamedLayout, $name, $payload);
                """;
            command.Parameters.AddWithValue("$revisionId", sealedSnapshot.RevisionId.ToString("D"));
            command.Parameters.AddWithValue("$workspace", sealedSnapshot.Workspace.ToString());
            command.Parameters.AddWithValue("$createdAt", sealedSnapshot.CreatedAt.ToUnixTimeMilliseconds());
            command.Parameters.AddWithValue("$isNamedLayout", sealedSnapshot.IsNamedLayout ? 1 : 0);
            command.Parameters.AddWithValue("$name", (object?)sealedSnapshot.Name ?? DBNull.Value);
            command.Parameters.AddWithValue("$payload", LayoutIntegrity.Serialize(sealedSnapshot));
            await command.ExecuteNonQueryAsync(cancellationToken);
        }

        if (!sealedSnapshot.IsNamedLayout)
        {
            await using var trimCommand = connection.CreateCommand();
            trimCommand.Transaction = transaction;
            trimCommand.CommandText = """
                DELETE FROM workstation_layout_snapshots
                WHERE revision_id IN (
                    SELECT revision_id
                    FROM workstation_layout_snapshots
                    WHERE workspace = $workspace AND is_named_layout = 0
                    ORDER BY created_at DESC
                    LIMIT -1 OFFSET 10
                );
                """;
            trimCommand.Parameters.AddWithValue("$workspace", sealedSnapshot.Workspace.ToString());
            await trimCommand.ExecuteNonQueryAsync(cancellationToken);
        }

        await transaction.CommitAsync(cancellationToken);
    }

    public async Task<WorkspaceLayoutSnapshot?> LoadLatestValidAsync(
        WorkspaceKind workspace,
        CancellationToken cancellationToken = default)
    {
        var snapshots = await ListAsync(workspace, cancellationToken);
        return snapshots.FirstOrDefault(LayoutIntegrity.IsValid);
    }

    public async Task<WorkspaceLayoutSnapshot?> LoadLatestValidAsync(CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenAsync(cancellationToken);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT payload_json
            FROM workstation_layout_snapshots
            ORDER BY created_at DESC;
            """;
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        while (await reader.ReadAsync(cancellationToken))
        {
            var snapshot = LayoutIntegrity.Deserialize(reader.GetString(0));
            if (snapshot is not null && LayoutIntegrity.IsValid(snapshot))
            {
                return snapshot;
            }
        }

        return null;
    }

    public async Task<IReadOnlyList<WorkspaceLayoutSnapshot>> ListAsync(
        WorkspaceKind workspace,
        CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenAsync(cancellationToken);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT payload_json
            FROM workstation_layout_snapshots
            WHERE workspace = $workspace
            ORDER BY created_at DESC;
            """;
        command.Parameters.AddWithValue("$workspace", workspace.ToString());
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        var snapshots = new List<WorkspaceLayoutSnapshot>();
        while (await reader.ReadAsync(cancellationToken))
        {
            var snapshot = LayoutIntegrity.Deserialize(reader.GetString(0));
            if (snapshot is not null)
            {
                snapshots.Add(snapshot);
            }
        }

        return snapshots;
    }

    public async Task<WorkspaceLayoutSnapshot?> LoadNamedAsync(
        WorkspaceKind workspace,
        string name,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(name);
        await using var connection = await OpenAsync(cancellationToken);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT payload_json
            FROM workstation_layout_snapshots
            WHERE workspace = $workspace AND is_named_layout = 1 AND layout_name = $name
            ORDER BY created_at DESC;
            """;
        command.Parameters.AddWithValue("$workspace", workspace.ToString());
        command.Parameters.AddWithValue("$name", name);
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        while (await reader.ReadAsync(cancellationToken))
        {
            var snapshot = LayoutIntegrity.Deserialize(reader.GetString(0));
            if (snapshot is not null && LayoutIntegrity.IsValid(snapshot))
            {
                return snapshot;
            }
        }

        return null;
    }

    private async Task<SqliteConnection> OpenAsync(CancellationToken cancellationToken)
    {
        var connection = new SqliteConnection(_connectionString);
        await connection.OpenAsync(cancellationToken);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            CREATE TABLE IF NOT EXISTS workstation_layout_snapshots (
                revision_id TEXT NOT NULL PRIMARY KEY,
                workspace TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                is_named_layout INTEGER NOT NULL,
                layout_name TEXT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_workstation_layout_workspace_created
                ON workstation_layout_snapshots(workspace, created_at DESC);
            """;
        await command.ExecuteNonQueryAsync(cancellationToken);
        return connection;
    }
}
