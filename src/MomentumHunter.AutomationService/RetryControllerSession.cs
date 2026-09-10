using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;

namespace MomentumHunter.AutomationService;

public sealed class TopologyNotYetStableException(string message) : Exception(message);

public sealed record RuntimeTopologyRule(string Role, string Executable, string ExecutableSha256,
    string CommandLine, string ParentRole, int Minimum, int Maximum);

/// <summary>Controller-side custody and exact host/target handshake. No SCM mutation here.</summary>
public sealed class RetryControllerSession : IDisposable
{
    private readonly ControllerJobCustody custody;
    private readonly NamedPipeServerStream pipe;
    private readonly RuntimeLaunchContract contract;
    private readonly string path;
    private readonly string hash;
    private string? nonce;
    private ProcessTopologyIdentity? launcher;
    private ContainedIdentity? target;
    private bool commitRequested;
    private bool committed;
    private bool disposed;
    private static readonly List<ControllerJobCustody> UnresolvedCustodyUntilProcessExit = new();
    public string ContractPath => path;
    public string ContractHash => hash;
    public ContainedIdentity Target => target ?? throw new InvalidOperationException("TARGET_NOT_ADMITTED");
    public IReadOnlyList<int> MemberPids() => custody.MemberPids();
    public ProcessTopologyIdentity InspectMember(int pid) => custody.InspectMember(pid);

    public RetryControllerSession(string path, ProcessStartInfo target, string serviceSid,
        int serviceSession, Dictionary<string, string> staticFiles, TimeSpan duration)
    {
        if (!Path.IsPathFullyQualified(path) || duration <= TimeSpan.Zero || duration > TimeSpan.FromMinutes(30))
            throw new ArgumentException("BOUNDED_ABSOLUTE_RETRY_CONTRACT_REQUIRED");
        this.path = Path.GetFullPath(path);
        custody = new();
        contract = new(1, custody.Identity.AttemptId, custody.Identity,
            "MH-Automation-Retry-" + custody.Identity.AttemptId, DateTimeOffset.UtcNow + duration,
            target.FileName, target.ArgumentList.ToArray(), target.WorkingDirectory, serviceSid, serviceSession,
            new Dictionary<string, string>(staticFiles, StringComparer.OrdinalIgnoreCase));
        try
        {
            pipe = new NamedPipeServerStream(contract.PipeName, PipeDirection.InOut, 1,
                PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
            var raw = JsonSerializer.SerializeToUtf8Bytes(contract, RetryLaunchGate.JsonOptions);
            hash = Convert.ToHexString(SHA256.HashData(raw));
            using var output = new FileStream(this.path, FileMode.CreateNew, FileAccess.Write, FileShare.Read,
                4096, FileOptions.WriteThrough);
            output.Write(raw); output.Flush(true);
        }
        catch { pipe?.Dispose(); custody.Dispose(); throw; }
    }

    public async Task AdmitAsync(ProcessTopologyIdentity expectedLauncher, CancellationToken cancel)
    {
        if (launcher is not null) throw new InvalidOperationException("DUPLICATE_LAUNCHER_ADMISSION");
        await pipe.WaitForConnectionAsync(cancel);
        Native.Require(GetNamedPipeClientProcessId(pipe.SafePipeHandle, out var pid), "PIPE_CLIENT_IDENTITY");
        if (pid != expectedLauncher.Pid) throw new InvalidOperationException("UNEXPECTED_PIPE_LAUNCHER");
        var actual = ProcessTopologyIdentity.Capture(pid, expectedLauncher.CreatedFileTime);
        if (actual != expectedLauncher || actual.UserSid != contract.ServiceUserSid || actual.SessionId != contract.ServiceSessionId)
            throw new InvalidOperationException("LAUNCHER_TOPOLOGY_IDENTITY_MISMATCH");
        var hello = await RetryLaunchGate.ReadFrameAsync(pipe, cancel);
        if (hello.Type != "HELLO" || hello.ContractHash != hash || hello.Target is not null
            || hello.LauncherPid != actual.Pid || hello.LauncherCreatedFileTime != actual.CreatedFileTime
            || !Guid.TryParseExact(hello.Nonce, "N", out _))
            throw new InvalidOperationException("LAUNCHER_HELLO_MISMATCH");
        launcher = actual; nonce = hello.Nonce;
        if (custody.MemberPids().Count != 0) throw new InvalidOperationException("OUTER_JOB_NOT_FRESH");
        custody.EnrollLauncher(actual);
        var initialMembers = custody.MemberPids();
        if (initialMembers.Count != 1 || initialMembers[0] != actual.Pid)
            throw new InvalidOperationException("LAUNCHER_NOT_EXCLUSIVELY_CONTAINED");
        await SendAsync("ADMIT", cancel);
        var suspended = await ReceiveAsync("SUSPENDED", cancel);
        var identity = suspended.Target ?? throw new InvalidOperationException("TARGET_IDENTITY_MISSING");
        var commandLine = string.Join(" ", new[] { contract.Executable }.Concat(contract.Arguments).Select(WindowsContainedProcess.Quote));
        if (identity.LauncherPid != launcher.Pid || identity.LauncherCreatedFileTime != launcher.CreatedFileTime
            || !WindowsContainedProcess.SamePath(identity.Executable, contract.Executable)
            || identity.ExecutableSha256 != contract.StaticFiles[Path.GetFullPath(contract.Executable)]
            || identity.CommandLine != commandLine || !WindowsContainedProcess.SamePath(identity.WorkingDirectory, contract.WorkingDirectory)
            || identity.UserSid != contract.ServiceUserSid || identity.SessionId != contract.ServiceSessionId)
            throw new InvalidOperationException("TARGET_CONTRACT_IDENTITY_MISMATCH");
        var members = custody.MemberPids().Where(value => value != launcher.Pid).ToArray();
        ProcessTopologyIdentity.ValidateSuspended(identity,
            ProcessTopologyIdentity.Capture(identity.TargetPid, identity.TargetCreatedFileTime), members);
        target = identity;
        await SendAsync("RESUME", cancel);
        var running = await ReceiveAsync("RUNNING", cancel);
        if (running.Target != identity) throw new InvalidOperationException("RUNNING_TARGET_IDENTITY_DRIFT");
    }

    public async Task CheckAsync(IReadOnlyList<RuntimeTopologyRule> rules, CancellationToken cancel)
    {
        using var bound = CancellationTokenSource.CreateLinkedTokenSource(cancel);
        bound.CancelAfter(TimeSpan.FromSeconds(15));
        while (true)
        {
            bound.Token.ThrowIfCancellationRequested();
            try { ValidateRunningTopology(rules); break; }
            catch (TopologyNotYetStableException) { await Task.Delay(25, bound.Token); }
        }
        await SendAsync("CHECK", cancel);
        var result = await ReceiveAsync("STATUS", cancel);
        if (result.Target != Target) throw new InvalidOperationException("STATUS_IDENTITY_DRIFT");
    }

    public void ValidateRunningTopology(IReadOnlyList<RuntimeTopologyRule> rules)
    {
        if (launcher is null || target is null) throw new InvalidOperationException("NO_ADMITTED_TOPOLOGY");
        var ids = custody.MemberPids();
        if (ids.Count != ids.Distinct().Count() || !ids.Contains(launcher.Pid) || !ids.Contains(target.TargetPid))
            throw new InvalidOperationException("REQUIRED_PROCESS_ROLE_MISSING");
        var observed = new Dictionary<int, ProcessTopologyIdentity>();
        foreach (var pid in ids)
        {
            observed.Add(pid, custody.InspectMember(pid));
        }
        if (observed[launcher.Pid] != launcher) throw new InvalidOperationException("LAUNCHER_IDENTITY_DRIFT");
        var root = observed[target.TargetPid];
        ProcessTopologyIdentity.ValidateSuspended(target, root, new[] { target.TargetPid });
        var roles = new Dictionary<int, string> { [launcher.Pid] = "LAUNCHER", [root.Pid] = "PYTHON_TARGET" };
        var pending = observed.Values.Where(p => !roles.ContainsKey(p.Pid)).ToList();
        var counts = rules.ToDictionary(rule => rule.Role, _ => 0, StringComparer.Ordinal);
        if (counts.Keys.Any(role => role is "LAUNCHER" or "PYTHON_TARGET")) throw new InvalidOperationException("RESERVED_ROLE");
        while (pending.Count > 0)
        {
            var progressed = false;
            foreach (var item in pending.ToArray())
            {
                if (!roles.TryGetValue(item.ParentPid, out var parentRole)) continue;
                var matches = rules.Where(rule => rule.ParentRole == parentRole
                    && WindowsContainedProcess.SamePath(rule.Executable, item.Executable)
                    && rule.ExecutableSha256 == item.ExecutableSha256 && rule.CommandLine == item.CommandLine).ToArray();
                if (matches.Length != 1 || item.CreatedFileTime < observed[item.ParentPid].CreatedFileTime
                    || item.UserSid != root.UserSid || item.SessionId != root.SessionId)
                    throw new InvalidOperationException("UNEXPECTED_AUTHORITY_BEARING_DESCENDANT:" + item.Executable + ":parent=" + parentRole
                        + ":command=" + (Path.GetFileName(item.Executable).Equals("conhost.exe",StringComparison.OrdinalIgnoreCase) ? item.CommandLine : "HASH:" + Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(item.CommandLine)))));
                roles.Add(item.Pid, matches[0].Role); counts[matches[0].Role]++;
                pending.Remove(item); progressed = true;
            }
            if (!progressed) throw new InvalidOperationException("WRONG_PARENT_OR_CYCLIC_TOPOLOGY");
        }
        if (rules.Any(rule => rule.Minimum < 0 || rule.Maximum < rule.Minimum || counts[rule.Role] > rule.Maximum))
            throw new InvalidOperationException("RUNTIME_ROLE_CARDINALITY_MISMATCH");
        if (rules.Any(rule => counts[rule.Role] < rule.Minimum))
            throw new TopologyNotYetStableException("REQUIRED_DESCENDANT_NOT_YET_PRESENT");
        var after = custody.MemberPids();
        if (!after.Order().SequenceEqual(ids.Order()))
            throw new TopologyNotYetStableException("TOPOLOGY_CHANGED_DURING_VALIDATION");
    }

    public async Task CommitPermanentAsync(CancellationToken cancel)
    {
        if (committed || commitRequested || target is null
            || RetryDecision.Read(path, hash, contract.AttemptId) == RetryDecision.Abort)
            throw new InvalidOperationException("INVALID_COMMIT_PHASE");
        commitRequested = true;
        await SendAsync("COMMIT_PERMANENT_SERVICE", cancel);
        var ack = await ReceiveAsync("COMMITTED", cancel);
        if (ack.Target != target) throw new InvalidOperationException("COMMIT_TARGET_MISMATCH");
        ReconcileCommit();
        if (!committed) throw new InvalidOperationException("DURABLE_COMMIT_MISSING");
    }

    public bool ReconcileCommit()
    {
        var receipt = path + ".permanent.json";
        if (!File.Exists(receipt)) return false;
        if (RetryDecision.Read(path, hash, contract.AttemptId) != RetryDecision.Commit)
            throw new InvalidOperationException("PERMANENT_DECISION_MISSING");
        RetryLaunchGate.ValidatePermanent(File.ReadAllBytes(receipt), hash, contract.AttemptId);
        var value = RetryLaunchGate.Decode<PermanentServiceReceipt>(File.ReadAllBytes(receipt));
        if (!commitRequested || value.Nonce != nonce || value.LauncherPid != launcher?.Pid
            || value.LauncherCreatedFileTime != launcher?.CreatedFileTime)
            throw new InvalidOperationException("UNAUTHORIZED_PERMANENT_RECEIPT");
        committed = true; return true;
    }

    public void Abort()
    {
        // A missing receipt is not a cancellation fence. Reserve the competing
        // decision before any native termination or caller-owned SCM stop.
        if (RetryDecision.Reserve(path, hash, contract.AttemptId, RetryDecision.Abort) != RetryDecision.Abort)
            throw new InvalidOperationException(ReconcileCommit()
                ? "PERMANENT_CUSTODY_ALREADY_COMMITTED" : "COMMIT_OUTCOME_UNKNOWN");
        if (File.Exists(path + ".permanent.json")) throw new InvalidOperationException("CONTRADICTORY_RETRY_DECISION");
        custody.Abort();
        var timer = Stopwatch.StartNew();
        while (custody.MemberPids().Count != 0)
        { if (timer.Elapsed > TimeSpan.FromSeconds(10)) throw new TimeoutException("OUTER_JOB_QUIESCENCE_UNPROVEN"); Thread.Yield(); }
    }

    private Task SendAsync(string type, CancellationToken cancel) => RetryLaunchGate.WriteFrameAsync(pipe,
        new(type, hash, nonce ?? throw new InvalidOperationException("NO_HOST_NONCE")), cancel);
    private async Task<RetryFrame> ReceiveAsync(string type, CancellationToken cancel)
    {
        var frame = await RetryLaunchGate.ReadFrameAsync(pipe, cancel);
        if (frame.Type != type || frame.ContractHash != hash || frame.Nonce != nonce)
            throw new InvalidOperationException("CONTROLLER_FRAME_IDENTITY_OR_PHASE_MISMATCH");
        return frame;
    }

    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        var quiesced = false;
        try
        {
            // Once COMMIT may be in flight, disposal is not another decision.
            // Preserve the terminal UNKNOWN classification for explicit reconciliation.
            if (!commitRequested) { Abort(); quiesced = true; }
        }
        catch (InvalidOperationException e) when (e.Message is "PERMANENT_CUSTODY_ALREADY_COMMITTED" or "COMMIT_OUTCOME_UNKNOWN") { }
        finally
        {
            pipe.Dispose();
            if (quiesced) custody.Dispose();
            else
            {
                // Ordinary disposal cannot close the last O handle while the host
                // is between its irrevocable commit reservation and BorrowJob.
                // Process death still closes O; no continuity is claimed then.
                lock (UnresolvedCustodyUntilProcessExit) UnresolvedCustodyUntilProcessExit.Add(custody);
            }
        }
    }

    [DllImport("kernel32", SetLastError = true)]
    private static extern bool GetNamedPipeClientProcessId(Microsoft.Win32.SafeHandles.SafePipeHandle pipe, out int pid);
}
