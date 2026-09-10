using System.Diagnostics;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;
using MomentumHunter.AutomationService;

namespace MomentumHunter.Integration.Tests;

public sealed class PrechildCommitRaceTests
{
    private static string Env(string name) => Environment.GetEnvironmentVariable(name)
        ?? throw new InvalidOperationException("Physical binding required: " + name);

    [Theory]
    [InlineData("BeforeReservation", false)]
    [InlineData("BeforeReservation", true)]
    [InlineData("ReservedBeforePublication", false)]
    [InlineData("ReservedBeforePublication", true)]
    [InlineData("PublishedBeforeBorrow", false)]
    [InlineData("PublishedBeforeBorrow", true)]
    [InlineData("Borrowed", true)]
    public async Task CompetingAbortAndDisposeCannotCrossIrrevocableCommitDecision(string barrier, bool dispose)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var root = Directory.CreateTempSubdirectory("MH-Prechild-Commit-").FullName;
        Directory.CreateDirectory(Path.Combine(root, "momentum_hunter"));
        File.WriteAllText(Path.Combine(root, "momentum_hunter", "__init__.py"), "");
        File.WriteAllText(Path.Combine(root, "momentum_hunter", "automation_supervisor.py"),
            "open('first.txt','x').write('first')\nimport time\ntime.sleep(120)\n");
        var manifest = Path.Combine(root, "manifest.json"); File.WriteAllText(manifest, "{}");
        var python = Env("MH_CONTAINMENT_TEST_PYTHON");
        var probe = Env("MH_CONTAINMENT_TEST_PROBE");
        var info = new ProcessStartInfo(python) { WorkingDirectory = root, UseShellExecute = false };
        foreach (var arg in new[] { "-B", "-m", "momentum_hunter.automation_supervisor", "run", "--manifest", manifest }) info.ArgumentList.Add(arg);
        var files = RetryLaunchGate.RequiredStaticFiles(info, probe).ToDictionary(Path.GetFullPath,
            p => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(p))), StringComparer.OrdinalIgnoreCase);
        using var self = Process.GetCurrentProcess();
        using var controller = new RetryControllerSession(Path.Combine(root, "launch-contract.json"), info,
            WindowsIdentity.GetCurrent().User!.Value, self.SessionId, files, TimeSpan.FromMinutes(2));
        var start = new ProcessStartInfo(probe) { WorkingDirectory = root, UseShellExecute = false,
            CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var arg in new[] { "decision-host", root, python, probe, barrier }) start.ArgumentList.Add(arg);
        using var host = Process.Start(start)!;
        _ = host.SafeHandle;
        var stderr = host.StandardError.ReadToEndAsync();
        var lines = new List<string>();
        using var bound = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        Process? target = null;
        try
        {
            await controller.AdmitAsync(ProcessTopologyIdentity.Capture(host.Id,
                host.StartTime.ToUniversalTime().ToFileTimeUtc()), bound.Token);
            target = Process.GetProcessById(controller.Target.TargetPid); _ = target.SafeHandle;
            Assert.Equal(controller.Target.TargetCreatedFileTime, target.StartTime.ToUniversalTime().ToFileTimeUtc());
            using var ack = new CancellationTokenSource();
            var commit = controller.CommitPermanentAsync(ack.Token);
            while (true)
            {
                var line = await host.StandardOutput.ReadLineAsync(bound.Token)
                    ?? throw new InvalidOperationException("PROBE_EARLY_EXIT:" + await stderr);
                lines.Add(line);
                using var value = JsonDocument.Parse(line);
                if (value.RootElement.GetProperty("stage").GetString() == barrier) break;
            }
            ack.Cancel();
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => commit);
            var receipt = controller.ContractPath + ".permanent.json";
            if (barrier == "BeforeReservation" && !dispose)
            {
                controller.Abort();
                await host.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
                Assert.False(File.Exists(receipt));
                Assert.Empty(controller.MemberPids());
                Assert.Equal(RetryDecision.Abort, RetryDecision.Read(controller.ContractPath, controller.ContractHash,
                    RetryLaunchGate.Decode<RuntimeLaunchContract>(File.ReadAllBytes(controller.ContractPath)).AttemptId));
            }
            else
            {
                Assert.Equal(barrier is "PublishedBeforeBorrow" or "Borrowed", File.Exists(receipt));
                if (barrier != "BeforeReservation")
                {
                    var failure = Assert.Throws<InvalidOperationException>(() => controller.Abort());
                    Assert.Equal(barrier == "ReservedBeforePublication" ? "COMMIT_OUTCOME_UNKNOWN" : "PERMANENT_CUSTODY_ALREADY_COMMITTED", failure.Message);
                }
                if (dispose) controller.Dispose();
                Assert.False(host.HasExited); Assert.False(target.HasExited);
                await host.StandardInput.WriteLineAsync("continue");
                if (barrier != "Borrowed")
                {
                    while (true)
                    {
                        var line = await host.StandardOutput.ReadLineAsync(bound.Token)
                            ?? throw new InvalidOperationException("PROBE_EARLY_EXIT:" + await stderr);
                        lines.Add(line);
                        using var value = JsonDocument.Parse(line);
                        if (value.RootElement.GetProperty("stage").GetString() == "Borrowed") break;
                    }
                }
                Assert.True(controller.ReconcileCommit());
                Assert.False(host.HasExited); Assert.False(target.HasExited);
            }
            File.WriteAllText(Path.Combine(root, "decision-race-proof.json"), JsonSerializer.Serialize(new {
                barrier, dispose, decision = File.ReadAllText(controller.ContractPath + ".decision.json"),
                receiptPresent = File.Exists(receipt), ordinaryPostcommitTermination = false,
                actualProductionClasses = true, installedScmTest = false, providerContact = false }));
        }
        finally
        {
            if (!host.HasExited) host.Kill(); // Exact disposable fixture handle, not ordinary controller cleanup.
            await host.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
            if (target is not null) { await target.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15)); target.Dispose(); }
            File.WriteAllLines(Path.Combine(root, "decision-transcript.jsonl"), lines);
            File.WriteAllText(Path.Combine(root, "stderr.txt"), await stderr);
        }
    }

    [Fact]
    public async Task ConcurrentReservationHasOneWinnerAndNeverChanges()
    {
        var root = Directory.CreateTempSubdirectory("MH-Prechild-Decision-").FullName;
        for (var iteration = 0; iteration < 30; iteration++)
        {
            var path = Path.Combine(root, iteration + ".json");
            var attempt = Guid.NewGuid().ToString("N");
            using var barrier = new Barrier(2);
            Task<string> Claim(string choice) => Task.Run(() => {
                Assert.True(barrier.SignalAndWait(TimeSpan.FromSeconds(10)));
                return RetryDecision.Reserve(path, new string('A',64), attempt, choice);
            });
            var results = await Task.WhenAll(Claim(RetryDecision.Commit), Claim(RetryDecision.Abort));
            Assert.Equal(results[0], results[1]);
            Assert.Equal(results[0], RetryDecision.Reserve(path, new string('A',64), attempt, RetryDecision.Abort));
            Assert.Equal(results[0], RetryDecision.Reserve(path, new string('A',64), attempt, RetryDecision.Commit));
        }
    }
}
