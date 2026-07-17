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
    private ISingleInstanceCoordinator? _singleInstance;
    private IApplicationLifetimeCoordinator? _lifetime;
    private IBackgroundCollectionService? _backgroundCollection;
    private ITrayService? _tray;
    private MainWindow? _window;
    private bool _activationRequestedWhileStarting;

    private async void OnStartup(object sender, StartupEventArgs e)
    {
        ShutdownMode = ShutdownMode.OnExplicitShutdown;
        _singleInstance = new SingleInstanceCoordinator();
        if (!_singleInstance.TryAcquirePrimary())
        {
            _singleInstance.SignalPrimary();
            Shutdown(0);
            return;
        }

        _singleInstance.ActivationRequested += OnPrimaryActivationRequested;
        SessionEnding += OnSessionEnding;

        var settingsDirectory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MomentumHunter");
        var services = new ServiceCollection();
        services.AddSingleton<IEngineClient, MockEngineClient>();
        services.AddSingleton<IPythonEngineHostConnection>(_ =>
            new PythonEngineHostConnection(PythonEngineHostOptions.CreateDefault()));
        services.AddSingleton<IReadOnlyWorkspaceClient>(serviceProvider =>
            new PythonReadOnlyWorkspaceClient(serviceProvider.GetRequiredService<IPythonEngineHostConnection>()));
        services.AddSingleton<IWorkspaceLayoutStore>(_ =>
            new SqliteWorkspaceLayoutStore(Path.Combine(settingsDirectory, "workstation-layouts.db")));
        services.AddSingleton<ITraySettingsStore>(_ =>
            new JsonTraySettingsStore(Path.Combine(settingsDirectory, "background-collection-settings.json")));
        services.AddSingleton<IBackgroundCollectionService>(serviceProvider =>
            new RemoteBackgroundCollectionService(serviceProvider.GetRequiredService<IPythonEngineHostConnection>()));
        services.AddSingleton<ITrayService, NotifyIconTrayService>();
        services.AddSingleton<INotificationService, WpfNotificationService>();
        services.AddSingleton<IApplicationLifetimeCoordinator, ApplicationLifetimeCoordinator>();
        services.AddSingleton<ShellViewModel>(serviceProvider => new ShellViewModel(
            serviceProvider.GetRequiredService<IEngineClient>(),
            serviceProvider.GetRequiredService<IWorkspaceLayoutStore>(),
            serviceProvider.GetRequiredService<IReadOnlyWorkspaceClient>()));
        services.AddSingleton<MainWindow>();
        _services = services.BuildServiceProvider();

        _lifetime = _services.GetRequiredService<IApplicationLifetimeCoordinator>();
        _backgroundCollection = _services.GetRequiredService<IBackgroundCollectionService>();
        _tray = _services.GetRequiredService<ITrayService>();
        _window = _services.GetRequiredService<MainWindow>();
        _backgroundCollection.StatusChanged += OnBackgroundStatusChanged;
        _backgroundCollection.ActivityRecorded += OnBackgroundActivityRecorded;
        _tray.OpenRequested += OnTrayOpenRequested;
        _tray.PauseOrResumeRequested += OnTrayPauseOrResumeRequested;
        _tray.RunScanNowRequested += OnTrayRunScanNowRequested;
        _tray.SystemStatusRequested += OnTraySystemStatusRequested;
        _tray.ExitRequested += OnTrayExitRequested;

        await _window.InitializeAsync();
        await _lifetime.InitializeAsync();
        _window.Show();
        if (_activationRequestedWhileStarting)
        {
            _activationRequestedWhileStarting = false;
            _lifetime.RestoreWorkstation(_window);
        }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _tray?.Dispose();
        if (_backgroundCollection is not null)
        {
            _backgroundCollection.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }

        _lifetime?.Dispose();
        _singleInstance?.Dispose();
        _services?.Dispose();
        base.OnExit(e);
    }

    private void OnPrimaryActivationRequested(object? sender, EventArgs e)
    {
        Dispatcher.BeginInvoke(() =>
        {
            if (_window is null || _lifetime is null)
            {
                _activationRequestedWhileStarting = true;
                return;
            }

            _lifetime.RestoreWorkstation(_window);
        });
    }

    private void OnBackgroundStatusChanged(BackgroundCollectionStatus status) =>
        Dispatcher.BeginInvoke(() => _window?.UpdateBackgroundStatus(status));

    private void OnBackgroundActivityRecorded(BackgroundCollectionActivity activity) =>
        Dispatcher.BeginInvoke(() => _window?.RecordBackgroundActivity(activity));

    private void OnTrayOpenRequested(object? sender, EventArgs e)
    {
        DispatchToWorkstation(() =>
        {
            if (_window is not null && _lifetime is not null)
            {
                _lifetime.RestoreWorkstation(_window);
            }
        });
    }

    private async void OnTrayPauseOrResumeRequested(object? sender, EventArgs e) =>
        await DispatchToWorkstationAsync(() => _lifetime?.PauseOrResumeAsync() ?? Task.CompletedTask);

    private async void OnTrayRunScanNowRequested(object? sender, EventArgs e) =>
        await DispatchToWorkstationAsync(async () =>
        {
            if (_lifetime is not null)
            {
                await _lifetime.RunScanNowAsync();
            }
        });

    private void OnTraySystemStatusRequested(object? sender, EventArgs e)
    {
        DispatchToWorkstation(() =>
        {
            if (_window is not null && _lifetime is not null)
            {
                _lifetime.OpenSystemStatus(_window);
            }
        });
    }

    private async void OnTrayExitRequested(object? sender, EventArgs e) =>
        await DispatchToWorkstationAsync(() => _window?.RequestExplicitExitFromUiAsync() ?? Task.CompletedTask);

    private void DispatchToWorkstation(Action action)
    {
        if (Dispatcher.CheckAccess())
        {
            action();
            return;
        }

        Dispatcher.BeginInvoke(action);
    }

    private Task DispatchToWorkstationAsync(Func<Task> action)
    {
        if (Dispatcher.CheckAccess())
        {
            return action();
        }

        return Dispatcher.InvokeAsync(action).Task.Unwrap();
    }

    private void OnSessionEnding(object? sender, SessionEndingCancelEventArgs e)
    {
        if (_window is not null && _lifetime is not null)
        {
            _window.AllowApplicationShutdown();
            _lifetime.RequestExplicitExitAsync(_window, isSessionEnding: true).GetAwaiter().GetResult();
        }
    }
}
