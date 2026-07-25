using System.Drawing;
using System.Windows.Threading;
using Forms = System.Windows.Forms;
using MomentumHunter.Application;

namespace MomentumHunter.Desktop.Wpf;

public sealed class NotifyIconTrayService : ITrayService
{
    private readonly Dispatcher _dispatcher = System.Windows.Application.Current?.Dispatcher ?? Dispatcher.CurrentDispatcher;
    private Forms.NotifyIcon? _notifyIcon;
    private Icon? _applicationIcon;
    private Forms.ToolStripMenuItem? _statusItem;
    private Forms.ToolStripMenuItem? _pauseOrResumeItem;
    private Forms.ToolStripMenuItem? _runScanNowItem;

    public event EventHandler? OpenRequested;

    public event EventHandler? PauseOrResumeRequested;

    public event EventHandler? RunScanNowRequested;

    public event EventHandler? SystemStatusRequested;

    public event EventHandler? ExitRequested;

    public void Initialize()
    {
        if (!EnsureDispatcher(Initialize))
        {
            return;
        }

        if (_notifyIcon is not null)
        {
            return;
        }

        var menu = new Forms.ContextMenuStrip();
        var heading = new Forms.ToolStripMenuItem(TrayMenuDefinition.Heading) { Enabled = false };
        _statusItem = new Forms.ToolStripMenuItem(TrayMenuDefinition.StatusLabel(new BackgroundCollectionStatus(BackgroundCollectionState.Starting, null, 0, 0, "Waiting for monitoring to start."))) { Enabled = false };
        var openItem = new Forms.ToolStripMenuItem(TrayMenuDefinition.OpenWorkstation);
        _pauseOrResumeItem = new Forms.ToolStripMenuItem(TrayMenuDefinition.PauseMonitoring);
        _runScanNowItem = new Forms.ToolStripMenuItem(TrayMenuDefinition.RunScanNow);
        var systemStatusItem = new Forms.ToolStripMenuItem(TrayMenuDefinition.ViewSystemStatus);
        var exitItem = new Forms.ToolStripMenuItem(TrayMenuDefinition.ExitMomentumHunter);

        openItem.Click += (_, _) => OpenRequested?.Invoke(this, EventArgs.Empty);
        _pauseOrResumeItem.Click += (_, _) => PauseOrResumeRequested?.Invoke(this, EventArgs.Empty);
        _runScanNowItem.Click += (_, _) => RunScanNowRequested?.Invoke(this, EventArgs.Empty);
        systemStatusItem.Click += (_, _) => SystemStatusRequested?.Invoke(this, EventArgs.Empty);
        exitItem.Click += (_, _) => ExitRequested?.Invoke(this, EventArgs.Empty);
        menu.Items.AddRange(
        [
            heading,
            _statusItem,
            new Forms.ToolStripSeparator(),
            openItem,
            _pauseOrResumeItem,
            _runScanNowItem,
            systemStatusItem,
            new Forms.ToolStripSeparator(),
            exitItem,
        ]);

        _applicationIcon = LoadApplicationIcon();
        _notifyIcon = new Forms.NotifyIcon
        {
            ContextMenuStrip = menu,
            Icon = _applicationIcon ?? SystemIcons.Application,
            Text = "Momentum Hunter - Starting",
            Visible = true,
        };
        _notifyIcon.DoubleClick += (_, _) => OpenRequested?.Invoke(this, EventArgs.Empty);
    }

    public void UpdateStatus(BackgroundCollectionStatus status)
    {
        if (!EnsureDispatcher(() => UpdateStatus(status)))
        {
            return;
        }

        if (_notifyIcon is null || _statusItem is null || _pauseOrResumeItem is null || _runScanNowItem is null)
        {
            return;
        }

        _statusItem.Text = TrayMenuDefinition.StatusLabel(status);
        _pauseOrResumeItem.Text = TrayMenuDefinition.PauseOrResumeLabel(status);
        _pauseOrResumeItem.Enabled = status.State is BackgroundCollectionState.Healthy or BackgroundCollectionState.Degraded or BackgroundCollectionState.Paused;
        _runScanNowItem.Enabled = status.State is not (BackgroundCollectionState.Paused or BackgroundCollectionState.Stopping);
        _notifyIcon.Text = CreateTooltip(status);
    }

    public void ShowNotification(string title, string message)
    {
        if (!EnsureDispatcher(() => ShowNotification(title, message)))
        {
            return;
        }

        if (_notifyIcon is null)
        {
            return;
        }

        _notifyIcon.BalloonTipTitle = title;
        _notifyIcon.BalloonTipText = message;
        _notifyIcon.ShowBalloonTip(4000);
    }

    public void Dispose()
    {
        if (!_dispatcher.CheckAccess())
        {
            if (!_dispatcher.HasShutdownStarted)
            {
                _dispatcher.Invoke(Dispose);
            }

            return;
        }

        if (_notifyIcon is null)
        {
            return;
        }

        _notifyIcon.Visible = false;
        _notifyIcon.Dispose();
        _notifyIcon = null;
        _applicationIcon?.Dispose();
        _applicationIcon = null;
        _statusItem = null;
        _pauseOrResumeItem = null;
        _runScanNowItem = null;
    }

    private bool EnsureDispatcher(Action action)
    {
        if (_dispatcher.CheckAccess())
        {
            return true;
        }

        if (!_dispatcher.HasShutdownStarted)
        {
            _dispatcher.BeginInvoke(action);
        }

        return false;
    }

    private static string CreateTooltip(BackgroundCollectionStatus status)
    {
        var lastScan = status.LastCompletedCycleAt is { } completed ? completed.ToLocalTime().ToString("HH:mm") : "pending";
        var text = $"Momentum Hunter | {status.State} | {status.MonitoredSymbolCount} symbols | {lastScan}";
        return text.Length <= 63 ? text : text[..63];
    }

    private static Icon? LoadApplicationIcon()
    {
        var processPath = Environment.ProcessPath;
        return string.IsNullOrWhiteSpace(processPath)
            ? null
            : Icon.ExtractAssociatedIcon(processPath);
    }
}
