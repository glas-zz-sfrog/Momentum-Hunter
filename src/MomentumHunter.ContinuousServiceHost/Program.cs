using MomentumHunter.ContinuousServiceHost;

var options = ContinuousServiceOptions.Create(args);
if (options.Role == "science")
{
    foreach (System.Collections.DictionaryEntry item in Environment.GetEnvironmentVariables())
        if (System.Text.RegularExpressions.Regex.IsMatch((string)item.Key,
            "SCHWAB|FINVIZ|ALPACA|IBKR|MH_CANARY|API_KEY|API_SECRET|OAUTH|ACCESS_TOKEN|REFRESH_TOKEN|^PYTHON",
            System.Text.RegularExpressions.RegexOptions.IgnoreCase)) Environment.SetEnvironmentVariable((string)item.Key, null);
}
var builder = Host.CreateApplicationBuilder(args);
builder.Services.AddWindowsService(serviceOptions =>
{
    serviceOptions.ServiceName = options.ServiceName;
});
builder.Services.AddSingleton(options);
if (options.Role == "science")
{
    builder.Logging.ClearProviders();
    if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Direct Science requires Windows SCM.");
    builder.Services.AddHostedService<DirectScienceService>();
}
else builder.Services.AddHostedService<ContinuousProcessWorker>();

builder.Services.Configure<HostOptions>(value => value.ShutdownTimeout = TimeSpan.FromSeconds(options.ShutdownSeconds + 15));
using var host = builder.Build();
if (options.ConsoleControl)
{
    _ = Task.Run(async () =>
    {
        while (await Console.In.ReadLineAsync() is { } line)
        {
            if (line != "STOP") continue;
            host.Services.GetRequiredService<IHostApplicationLifetime>().StopApplication();
            return;
        }
        host.Services.GetRequiredService<IHostApplicationLifetime>().StopApplication();
    });
}
await host.RunAsync();
