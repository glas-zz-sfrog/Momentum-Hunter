using System.Text.Json.Nodes;

namespace MomentumHunter.ContinuousServiceHost;

[System.Runtime.Versioning.SupportedOSPlatform("windows")]
internal sealed class DirectScienceService(ContinuousServiceOptions options, IHostApplicationLifetime lifetime) : BackgroundService
{
    protected override Task ExecuteAsync(CancellationToken stoppingToken) => Task.Factory.StartNew(() =>
    {
        if (!options.Qualification || options.Role != "science" || options.ConsoleControl)
            throw new InvalidDataException("DIRECT_SCIENCE_REQUIRES_QUALIFICATION_SCM");
        using var configLease = new FileStream(options.ConfigPath, FileMode.Open, FileAccess.Read, FileShare.Read);
        using var configBuffer = new MemoryStream();
        configLease.CopyTo(configBuffer);
        var configBytes = configBuffer.ToArray();
        var config = JsonNode.Parse(configBytes)!.AsObject();
        var science = config["host"]!["science"]!;
        if (science["hostingModel"]?.GetValue<string>() != "SCM_DIRECT_SCIENCE_SERVICE_PROCESS" ||
            science["principal"]?.GetValue<string>() != @"NT SERVICE\" + options.ServiceName ||
            science["restrictingSid"]?.GetValue<string>() != ScienceServiceDaclPolicy.ServiceSid(options.ServiceName))
            throw new InvalidDataException("DIRECT_SCIENCE_IDENTITY_MISMATCH");
        var log = Path.Combine(config["logRoot"]!.GetValue<string>(), "science");
        try
        {
            using var image = new DirectScienceImage(options, config);
            using var targets = ScienceQualificationTargets.Open(options, config, configBytes, image);
            var plan = JsonNode.Parse(File.ReadAllBytes(image.Resolve("science-authority.json")))!.AsObject();
            var authority = DirectScienceAuthority.Inspect(options.ServiceName, plan, config, options.ConfigPath, targets);
            Save(log, "authority-" + Environment.ProcessId + ".json", authority);
            if (authority["status"]!.GetValue<string>() != "PASS") throw new InvalidDataException("SCIENCE_EFFECTIVE_AUTHORITY_FAILED");
            targets?.Attest("AFTER_GUARD");
            using var generation = new DirectScienceGeneration(config);
            using var stop = new EventWaitHandle(false, EventResetMode.ManualReset);
            using var registration = stoppingToken.Register(() => stop.Set());
            targets?.StartMonitoring(() => stop.Set());
            var code = image.Run(options.ConfigPath, generation.Generation, stop.SafeWaitHandle.DangerousGetHandle());
            targets?.FinishMonitoring();
            targets?.Attest("AFTER_GENERATION");
            if (targets != null) Save(log, "target-binding-" + generation.Generation + ".json", targets.Evidence());
            Save(log, "network-bootstrap-" + generation.Generation + ".json", new JsonObject {
                ["generation"] = generation.Generation, ["processId"] = Environment.ProcessId,
                ["deniedAttempts"] = image.NetworkDeniedAttempts, ["pythonResult"] = code,
                ["scope"] = "EARLY_PYTHON_AUDIT_NOT_NATIVE_FIREWALL", ["source"] = "ACTUAL_EMBEDDED_INTERPRETER"
            });
            generation.Returned(code);
            Environment.ExitCode = code;
        }
        catch (Exception ex)
        {
            Environment.ExitCode = 2;
            Save(log, "host-failure-" + Guid.NewGuid().ToString("N") + ".json",
                System.Text.Json.JsonSerializer.SerializeToNode(new { atUtc = DateTimeOffset.UtcNow, exception = ex.GetType().FullName,
                    ex.Message, details = ex.ToString(), processId = Environment.ProcessId, result = "INCOMPLETE", providerContact = false })!.AsObject());
        }
        finally { lifetime.StopApplication(); }
    }, CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);

    private static void Save(string log, string name, JsonObject record)
    {
        using var file = new FileStream(Path.Combine(log, name), FileMode.CreateNew, FileAccess.Write, FileShare.Read);
        System.Text.Json.JsonSerializer.Serialize(file, record);
        file.Flush(true);
    }
}
