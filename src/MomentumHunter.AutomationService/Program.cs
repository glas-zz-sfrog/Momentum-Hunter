using MomentumHunter.AutomationService;

var builder = Host.CreateApplicationBuilder(args);
builder.Services.AddWindowsService(options =>
{
    options.ServiceName = ServiceIdentity.ServiceName;
});
builder.Services.AddSingleton(PythonAutomationSupervisorOptions.Create(args));
builder.Services.AddHostedService<PythonAutomationSupervisorWorker>();

await builder.Build().RunAsync();
