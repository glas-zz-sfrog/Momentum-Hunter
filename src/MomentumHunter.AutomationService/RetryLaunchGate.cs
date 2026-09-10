using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace MomentumHunter.AutomationService;

public sealed record RuntimeLaunchContract(int SchemaVersion, string AttemptId,
    ControllerIdentity Controller, string PipeName, DateTimeOffset DeadlineUtc,
    string Executable, string[] Arguments, string WorkingDirectory,
    string ServiceUserSid, int ServiceSessionId, Dictionary<string, string> StaticFiles);

public sealed record RetryFrame(string Type, string ContractHash, string Nonce,
    ContainedIdentity? Target = null, int LauncherPid = 0, long LauncherCreatedFileTime = 0);

public sealed record PermanentServiceReceipt(int SchemaVersion, string ContractHash,
    string AttemptId, DateTimeOffset CommittedAtUtc, int LauncherPid,
    long LauncherCreatedFileTime, string Nonce);

/// <summary>Persistent retry selector and authenticated local controller admission.</summary>
public sealed class RetryLaunchGate : IDisposable
{
    private readonly string path;
    private readonly string contractHash;
    private readonly FileStream ownership;
    private readonly List<FileStream> inputLocks;
    private readonly RuntimeLaunchContract contract;
    private NamedPipeClientStream? pipe;
    private KernelHandle? adoptedOuterJob;
    private readonly string nonce = Guid.NewGuid().ToString("N");
    private bool permanent;
    public bool HandoffComplete { get; private set; }
    private static readonly List<KernelHandle> PermanentJobsUntilProcessExit = new();
    public bool Permanent => permanent;
    public ControllerProcessLease? Controller { get; private set; }
    public string ContractHash => contractHash;
    public string PermanentReceiptPath => path + ".permanent.json";
    public static readonly JsonSerializerOptions JsonOptions = new()
    { UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow, MaxDepth = 20 };

    private RetryLaunchGate(string path, string hash, RuntimeLaunchContract contract,
        FileStream ownership, List<FileStream> locks)
    { this.path = path; contractHash = hash; this.contract = contract; this.ownership = ownership; inputLocks = locks; }

    public static async Task<RetryLaunchGate> OpenAsync(string? path, ProcessStartInfo info,
        CancellationToken cancel)
    {
        if (path is null || !Path.IsPathFullyQualified(path))
            throw new InvalidOperationException("PERSISTENT_LAUNCH_CONTRACT_REQUIRED");
        path = Path.GetFullPath(path);
        var locks = new List<FileStream>();
        FileStream? owner = null;
        RetryLaunchGate? gate = null;
        try
        {
            // The lock is OS-owned; stale filename existence never grants or denies custody.
            owner = new FileStream(path + ".owner", FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            var recordLock = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            locks.Add(recordLock);
            var raw = ReadBounded(recordLock, 1024 * 1024);
            var value = Decode<RuntimeLaunchContract>(raw);
            var hash = Convert.ToHexString(SHA256.HashData(raw));
            ValidateContract(value, info);
            var required = RequiredStaticFiles(info, Environment.ProcessPath!);
            if (required.Any(file => !value.StaticFiles.ContainsKey(file)))
                throw new InvalidOperationException("LAUNCH_STATIC_CLOSURE_INCOMPLETE");
            foreach (var file in value.StaticFiles)
            {
                if (!Path.IsPathFullyQualified(file.Key)) throw new InvalidOperationException("RELATIVE_STATIC_IDENTITY");
                var stream = new FileStream(file.Key, FileMode.Open, FileAccess.Read, FileShare.Read);
                locks.Add(stream);
                if (Convert.ToHexString(SHA256.HashData(stream)) != file.Value)
                    throw new InvalidOperationException("STATIC_INPUT_IDENTITY_DRIFT:" + file.Key);
            }
            gate = new(path, hash, value, owner, locks);
            if (Directory.EnumerateFiles(Path.GetDirectoryName(path)!, Path.GetFileName(gate.PermanentReceiptPath) + ".partial-*").Any())
                throw new InvalidOperationException("INCOMPLETE_PERMANENT_PUBLICATION");
            if (File.Exists(gate.PermanentReceiptPath))
            {
                ValidatePermanent(File.ReadAllBytes(gate.PermanentReceiptPath), hash, value.AttemptId);
                gate.permanent = true;
                gate.HandoffComplete = true;
                return gate;
            }
            gate.RequireDeadline();
            gate.Controller = new ControllerProcessLease(value.Controller);
            gate.pipe = new NamedPipeClientStream(".", value.PipeName, PipeDirection.InOut,
                PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancel);
            deadline.CancelAfter(TimeSpan.FromSeconds(10));
            await gate.pipe.ConnectAsync(deadline.Token);
            Native.Require(GetNamedPipeServerProcessId(gate.pipe.SafePipeHandle, out var server), "PIPE_SERVER_IDENTITY");
            if (server != value.Controller.Pid) throw new InvalidOperationException("WRONG_PIPE_CONTROLLER");
            gate.Controller.RequireAlive();
            using var process = Process.GetCurrentProcess();
            await gate.SendAsync(new("HELLO", hash, gate.nonce, LauncherPid: process.Id,
                LauncherCreatedFileTime: process.StartTime.ToUniversalTime().ToFileTimeUtc()), cancel);
            await gate.ExpectAsync("ADMIT", cancel);
            return gate;
        }
        catch
        {
            if (gate is not null) gate.Dispose();
            else { owner?.Dispose(); foreach (var item in locks) item.Dispose(); }
            throw;
        }
    }

    public async Task AdmitResumeAsync(WindowsContainedProcess target, CancellationToken cancel)
    {
        ProcessTopologyIdentity.ValidateSuspended(target.Identity,
            target.InspectMember(target.Identity.TargetPid), target.MemberPids());
        if (permanent) { target.Resume(); return; }
        RequireDeadline(); Controller!.RequireAlive();
        await SendAsync(new("SUSPENDED", contractHash, nonce, target.Identity), cancel);
        await ExpectAsync("RESUME", cancel);
        RequireDeadline(); Controller.RequireAlive();
        target.Resume();
        await SendAsync(new("RUNNING", contractHash, nonce, target.Identity), cancel);
    }

    public async Task MonitorAsync(WindowsContainedProcess target, CancellationToken cancel)
    {
        if (permanent) { await Task.Delay(Timeout.InfiniteTimeSpan, cancel); return; }
        while (true)
        {
            RequireDeadline(); Controller!.RequireAlive();
            var frame = await ReceiveAsync(cancel);
            if (frame.Type == "CHECK")
            {
                await SendAsync(new("STATUS", contractHash, nonce, target.Identity), cancel);
                continue;
            }
            if (frame.Type != "COMMIT_PERMANENT_SERVICE")
                throw new InvalidOperationException("RETRY_ABORT_OR_INVALID_PHASE:" + frame.Type);
            RequireDeadline(); Controller.RequireAlive();
            using var process = Process.GetCurrentProcess();
            var receipt = new PermanentServiceReceipt(1, contractHash, contract.AttemptId,
                DateTimeOffset.UtcNow, process.Id, process.StartTime.ToUniversalTime().ToFileTimeUtc(), nonce);
            PublishPermanent(PermanentReceiptPath, receipt);
            permanent = true;
            // Commit authority first, without a host alias that could defeat precommit death
            // revocation. Death in this gap can terminate the accepted instance; recovery must
            // create a fresh contained instance from the durable receipt, never claim continuity.
            adoptedOuterJob = Controller.BorrowJob();
            Controller.Dispose(); Controller = null;
            HandoffComplete = true;
            // ACK loss after publication is reconciled from this exact durable receipt.
            try { await SendAsync(new("COMMITTED", contractHash, nonce, target.Identity), cancel); }
            catch (IOException) { }
            pipe?.Dispose(); pipe = null;
            await Task.Delay(Timeout.InfiniteTimeSpan, cancel);
            return;
        }
    }

    public void RequireDeadline()
    {
        if (!permanent && DateTimeOffset.UtcNow >= contract.DeadlineUtc)
            throw new TimeoutException("RETRY_ABSOLUTE_DEADLINE_EXPIRED");
    }

    private async Task ExpectAsync(string type, CancellationToken cancel)
    {
        var value = await ReceiveAsync(cancel);
        if (value.Type != type || value.Target is not null || value.LauncherPid != 0 || value.LauncherCreatedFileTime != 0)
            throw new InvalidOperationException("RETRY_FRAME_PHASE_MISMATCH");
    }

    private async Task<RetryFrame> ReceiveAsync(CancellationToken cancel)
    {
        RequireDeadline();
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancel);
        var remaining = contract.DeadlineUtc - DateTimeOffset.UtcNow;
        timeout.CancelAfter(remaining);
        var frame = await ReadFrameAsync(pipe!, timeout.Token);
        if (frame.ContractHash != contractHash || frame.Nonce != nonce)
            throw new InvalidOperationException("RETRY_FRAME_IDENTITY_MISMATCH");
        Controller!.RequireAlive();
        return frame;
    }

    private Task SendAsync(RetryFrame frame, CancellationToken cancel) => WriteFrameAsync(pipe!, frame, cancel);

    public static void ValidateContract(RuntimeLaunchContract value, ProcessStartInfo info)
    {
        if (value.SchemaVersion != 1 || value.Controller is null || value.AttemptId != value.Controller.AttemptId
            || !Guid.TryParseExact(value.AttemptId, "N", out _) || value.PipeName != "MH-Automation-Retry-" + value.AttemptId
            || !WindowsContainedProcess.SamePath(value.Executable, info.FileName)
            || !WindowsContainedProcess.SamePath(value.WorkingDirectory, info.WorkingDirectory)
            || !value.Arguments.SequenceEqual(info.ArgumentList, StringComparer.Ordinal)
            || value.StaticFiles.Count == 0 || !value.StaticFiles.ContainsKey(Path.GetFullPath(info.FileName)))
            throw new InvalidOperationException("LAUNCH_CONTRACT_MISMATCH");
        using var self = Native.OpenProcess(0x1000 | 0x100000, false, Environment.ProcessId);
        var current = WindowsContainedProcess.ReadIdentity(self);
        if (current.Sid != value.ServiceUserSid || current.Session != value.ServiceSessionId
            || current.Sid != value.Controller.UserSid)
            throw new InvalidOperationException("SERVICE_USER_OR_SESSION_MISMATCH");
    }

    public static string[] RequiredStaticFiles(ProcessStartInfo info, string hostExecutable)
    {
        var manifestIndex = info.ArgumentList.IndexOf("--manifest");
        if (manifestIndex < 0 || manifestIndex + 1 >= info.ArgumentList.Count)
            throw new InvalidOperationException("MANIFEST_ARGUMENT_REQUIRED");
        var hostRoot = Path.GetDirectoryName(Path.GetFullPath(hostExecutable))!;
        return Directory.EnumerateFiles(hostRoot).Where(file => new[] { ".exe", ".dll", ".json" }
            .Contains(Path.GetExtension(file), StringComparer.OrdinalIgnoreCase))
            .Concat(new[] { info.FileName, info.ArgumentList[manifestIndex + 1],
                Path.Combine(info.WorkingDirectory, "momentum_hunter", "__init__.py"),
                Path.Combine(info.WorkingDirectory, "momentum_hunter", "automation_supervisor.py") })
            .Select(Path.GetFullPath).Distinct(StringComparer.OrdinalIgnoreCase).Order(StringComparer.OrdinalIgnoreCase).ToArray();
    }

    public static void ValidatePermanent(byte[] raw, string hash, string attempt)
    {
        var value = Decode<PermanentServiceReceipt>(raw);
        if (value.SchemaVersion != 1 || value.ContractHash != hash || value.AttemptId != attempt
            || value.LauncherPid <= 0 || value.LauncherCreatedFileTime <= 0
            || !Guid.TryParseExact(value.Nonce, "N", out _) || value.CommittedAtUtc > DateTimeOffset.UtcNow)
            throw new InvalidOperationException("PERMANENT_SERVICE_RECEIPT_INVALID");
    }

    private static void PublishPermanent(string path, PermanentServiceReceipt value)
    {
        var temporary = path + ".partial-" + Guid.NewGuid().ToString("N");
        using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None,
            4096, FileOptions.WriteThrough))
        { var raw = JsonSerializer.SerializeToUtf8Bytes(value, JsonOptions); file.Write(raw); file.Flush(true); }
        File.Move(temporary, path, false);
    }

    public static T Decode<T>(byte[] raw)
    {
        if (raw.Length > 1024 * 1024) throw new InvalidOperationException("JSON_BOUND_EXCEEDED");
        using var document = JsonDocument.Parse(raw, new JsonDocumentOptions { MaxDepth = 20 });
        void Check(JsonElement element)
        {
            if (element.ValueKind == JsonValueKind.Object)
            {
                var names = new HashSet<string>(StringComparer.Ordinal);
                foreach (var property in element.EnumerateObject())
                { if (!names.Add(property.Name)) throw new InvalidOperationException("DUPLICATE_JSON_FIELD"); Check(property.Value); }
            }
            else if (element.ValueKind == JsonValueKind.Array) foreach (var item in element.EnumerateArray()) Check(item);
        }
        Check(document.RootElement);
        return JsonSerializer.Deserialize<T>(raw, JsonOptions) ?? throw new InvalidOperationException("NULL_CONTRACT");
    }

    public static void ValidateJson(byte[] raw) => Decode<JsonElement>(raw);

    private static byte[] ReadBounded(Stream source, int limit)
    {
        if (source.Length > limit) throw new InvalidOperationException("INPUT_SIZE_BOUND");
        using var result = new MemoryStream(); source.CopyTo(result); return result.ToArray();
    }

    public static async Task<RetryFrame> ReadFrameAsync(Stream stream, CancellationToken cancel)
    {
        var length = new byte[4]; await stream.ReadExactlyAsync(length, cancel);
        var size = System.Buffers.Binary.BinaryPrimitives.ReadInt32LittleEndian(length);
        if (size <= 0 || size > 16384) throw new InvalidOperationException("PIPE_FRAME_BOUND");
        var raw = new byte[size]; await stream.ReadExactlyAsync(raw, cancel);
        return Decode<RetryFrame>(raw);
    }

    public static async Task WriteFrameAsync(Stream stream, RetryFrame frame, CancellationToken cancel)
    {
        var raw = JsonSerializer.SerializeToUtf8Bytes(frame, JsonOptions);
        if (raw.Length > 16384) throw new InvalidOperationException("PIPE_FRAME_BOUND");
        var length = new byte[4]; System.Buffers.Binary.BinaryPrimitives.WriteInt32LittleEndian(length, raw.Length);
        await stream.WriteAsync(length, cancel); await stream.WriteAsync(raw, cancel); await stream.FlushAsync(cancel);
    }

    public void Dispose()
    {
        pipe?.Dispose(); Controller?.Dispose();
        if (permanent && adoptedOuterJob is not null)
        {
            // The launcher is also a member. Closing its last Job handle in StopAsync would
            // kill the host before SCM observes graceful stop. OS process exit closes it.
            lock (PermanentJobsUntilProcessExit) PermanentJobsUntilProcessExit.Add(adoptedOuterJob);
            adoptedOuterJob = null;
        }
        else adoptedOuterJob?.Dispose();
        foreach (var item in inputLocks) item.Dispose(); ownership.Dispose();
    }

    [DllImport("kernel32", SetLastError = true)]
    private static extern bool GetNamedPipeServerProcessId(Microsoft.Win32.SafeHandles.SafePipeHandle pipe, out int pid);
}
