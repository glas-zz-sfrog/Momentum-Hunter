using MomentumHunter.ContinuousServiceHost;

var options = ContinuousServiceOptions.Create(args);
var builder = Host.CreateApplicationBuilder(args);
builder.Services.AddWindowsService(serviceOptions =>
{
    serviceOptions.ServiceName = options.ServiceName;
});
builder.Services.AddSingleton(options);
builder.Services.AddHostedService<ContinuousProcessWorker>();

await builder.Build().RunAsync();
