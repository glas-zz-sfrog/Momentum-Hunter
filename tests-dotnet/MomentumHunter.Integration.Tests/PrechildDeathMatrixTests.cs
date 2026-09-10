using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace MomentumHunter.Integration.Tests;

public sealed class PrechildDeathMatrixTests
{
    private static string Env(string name) => Environment.GetEnvironmentVariable(name)
        ?? throw new InvalidOperationException("Required physical test binding: " + name);

    [Theory]
    [InlineData("BeforeJob")]
    [InlineData("JobConfigured")]
    [InlineData("BeforeCreate")]
    [InlineData("CreatedSuspended")]
    [InlineData("Verified")]
    [InlineData("BeforeResume")]
    [InlineData("Resumed")]
    public async Task LauncherKilledAtEachNativeBarrierLeavesNoTarget(string barrier)
        => await Run("idle", barrier);

    [Theory]
    [InlineData("immediate")]
    [InlineData("multiple")]
    [InlineData("grandchild")]
    [InlineData("rapid")]
    [InlineData("native")]
    [InlineData("breakaway")]
    [InlineData("parent-exit")]
    public async Task LauncherDeathRevokesActualChildFamily(string mode) => await Run(mode, "family-running");

    [Theory]
    [InlineData("host-waiting")]
    [InlineData("running-family")]
    public async Task ActualControllerProcessDeathRevokesOrDeniesLauncherFamily(string stage)
        => await Run("controller", stage);

    private static async Task Run(string mode, string barrier)
    {
        var root = Directory.CreateTempSubdirectory("MH-Prechild-Death-").FullName;
        var start = new ProcessStartInfo(Env("MH_CONTAINMENT_TEST_PROBE")) { UseShellExecute = false,
            WorkingDirectory = root, CreateNoWindow = true, RedirectStandardInput = true,
            RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var arg in new[] { mode, root, Env("MH_CONTAINMENT_TEST_PYTHON"), Env("MH_CONTAINMENT_TEST_HOST"), barrier }) start.ArgumentList.Add(arg);
        using var probe = Process.Start(start) ?? throw new InvalidOperationException("PROBE_START_FAILED");
        _ = probe.SafeHandle;
        var probeBirth = probe.StartTime.ToUniversalTime().ToFileTimeUtc();
        var errors = probe.StandardError.ReadToEndAsync();
        var retained = new List<Process>();
        var transcript = new List<string>();
        using var bound = new CancellationTokenSource(TimeSpan.FromSeconds(45));
        try
        {
            while (true)
            {
                var line = await probe.StandardOutput.ReadLineAsync(bound.Token);
                if (line is null) throw new InvalidOperationException("PROBE_EARLY_EXIT:" + await errors);
                transcript.Add(line);
                using var json = JsonDocument.Parse(line);
                if (json.RootElement.GetProperty("stage").GetString() != barrier) continue;
                var identity = json.RootElement.GetProperty("identity");
                var reported = new Dictionary<int, long>();
                if (identity.ValueKind == JsonValueKind.Array)
                    foreach (var item in identity.EnumerateArray()) reported.Add(item.GetProperty("Pid").GetInt32(), item.GetProperty("Created").GetInt64());
                else if (identity.ValueKind == JsonValueKind.Object && identity.TryGetProperty("members", out var members))
                {
                    foreach (var item in members.EnumerateArray()) reported.Add(item.GetProperty("Pid").GetInt32(), item.GetProperty("Created").GetInt64());
                    if (mode == "rapid") Assert.True(identity.GetProperty("total").GetUInt32() >= 21);
                }
                foreach (var pid in Children(probe.Id).Concat(reported.Keys).Distinct())
                {
                    Process? process = null;
                    try
                    {
                        process = Process.GetProcessById(pid); _ = process.SafeHandle;
                        var birth = process.StartTime.ToUniversalTime().ToFileTimeUtc();
                        if (reported.TryGetValue(pid, out var expected))
                        {
                            if (birth != expected) throw new InvalidOperationException("PROBE_MEMBER_PID_REUSED");
                        }
                        else if (probe.HasExited || birth < probeBirth || !Children(probe.Id).Contains(pid))
                            throw new InvalidOperationException("PROBE_CHILD_IDENTITY_UNPROVEN");
                        retained.Add(process); process = null;
                    }
                    catch (ArgumentException) { }
                    finally { process?.Dispose(); }
                }
                break;
            }
            if (barrier is "BeforeJob" or "JobConfigured" or "BeforeCreate" or "CreatedSuspended" or "Verified" or "BeforeResume" or "host-waiting")
                Assert.False(File.Exists(Path.Combine(root, "first.txt")));
            probe.Kill(); // Exact retained launched handle, never a name or re-discovered PID.
            await probe.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
            foreach (var process in retained)
                await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
            var finalCensus = new List<object>();
            var liveChildren = new List<int>();
            foreach (var pid in Children(probe.Id))
            {
                try
                {
                    using var item = Process.GetProcessById(pid);
                    var wait = WaitForSingleObject(item.SafeHandle.DangerousGetHandle(), 0);
                    if (wait != 0 && wait != 258) throw new InvalidOperationException("FINAL_CHILD_KERNEL_STATE_UNPROVEN");
                    finalCensus.Add(new { pid, kernelWait = wait, terminated = wait == 0 });
                    if (wait == 258) liveChildren.Add(pid);
                }
                catch (ArgumentException) { finalCensus.Add(new { pid, exitedBeforeOpen = true }); }
            }
            // Toolhelp can retain a terminated entry after the retained process object
            // is signaled. The invariant is no live task code, not no stale census row.
            File.WriteAllText(Path.Combine(root, "final-child-kernel-census.json"), JsonSerializer.Serialize(finalCensus));
            Assert.Empty(liveChildren);
            File.WriteAllLines(Path.Combine(root, "transcript.jsonl"), transcript);
            File.WriteAllText(Path.Combine(root, "proof.json"), JsonSerializer.Serialize(new {
                mode, barrier, retainedCount = retained.Count, survivingTaskProcessCount = 0,
                noNameBasedTermination = true, providerContact = false }));
        }
        finally
        {
            File.WriteAllLines(Path.Combine(root, "transcript.jsonl"), transcript);
            if (!probe.HasExited) probe.Kill();
            await probe.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
            // Failure cleanup is restricted to the exact already-retained fixture objects.
            foreach (var process in retained) { if (!process.HasExited) process.Kill(); process.Dispose(); }
            File.WriteAllText(Path.Combine(root, "probe-stderr.txt"), await errors);
        }
    }

    // This census is corroborating evidence only. Kernel Job lifetime performs cleanup.
    private static int[] Children(int parent)
    {
        var handle = CreateToolhelp32Snapshot(2, 0);
        if (handle == new IntPtr(-1)) throw new System.ComponentModel.Win32Exception();
        try
        {
            var entry = new Entry { Size = (uint)Marshal.SizeOf<Entry>() };
            var result = new List<int>();
            if (!Process32FirstW(handle, ref entry)) throw new System.ComponentModel.Win32Exception();
            do { if (entry.Parent == parent) result.Add((int)entry.Pid); } while (Process32NextW(handle, ref entry));
            return result.ToArray();
        }
        finally { CloseHandle(handle); }
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct Entry { public uint Size, Usage, Pid; public UIntPtr Heap; public uint Module, Threads, Parent; public int Priority; public uint Flags; [MarshalAs(UnmanagedType.ByValTStr, SizeConst=260)] public string? Name; }
    [DllImport("kernel32", SetLastError=true)] private static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint pid);
    [DllImport("kernel32", SetLastError=true, CharSet=CharSet.Unicode)] private static extern bool Process32FirstW(IntPtr snapshot, ref Entry entry);
    [DllImport("kernel32", SetLastError=true, CharSet=CharSet.Unicode)] private static extern bool Process32NextW(IntPtr snapshot, ref Entry entry);
    [DllImport("kernel32")] private static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32")] private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
}
