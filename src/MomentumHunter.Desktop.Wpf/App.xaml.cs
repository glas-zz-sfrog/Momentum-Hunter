using System.IO;
using System.Windows;
using Microsoft.Extensions.DependencyInjection;
using MomentumHunter.Application;
using MomentumHunter.EngineBridge;
using MomentumHunter.Infrastructure;
using MomentumHunter.Presentation;

namespace MomentumHunter.Desktop.Wpf;

public partial class App : System.Windows.Application
{
    private ServiceProvider? _services;

    private async void OnStartup(object sender, StartupEventArgs e)
    {
        var services = new ServiceCollection();
        services.AddSingleton<IEngineClient, MockEngineClient>();
        services.AddSingleton<IWorkspaceLayoutStore>(_ =>
        {
            var directory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MomentumHunter");
            return new SqliteWorkspaceLayoutStore(Path.Combine(directory, "workstation-layouts.db"));
        });
        services.AddSingleton<ShellViewModel>(serviceProvider => new ShellViewModel(
            serviceProvider.GetRequiredService<IEngineClient>(),
            serviceProvider.GetRequiredService<IWorkspaceLayoutStore>()));
        services.AddSingleton<MainWindow>();
        _services = services.BuildServiceProvider();

        var window = _services.GetRequiredService<MainWindow>();
        await window.InitializeAsync();
        window.Show();
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _services?.Dispose();
        base.OnExit(e);
    }
}
