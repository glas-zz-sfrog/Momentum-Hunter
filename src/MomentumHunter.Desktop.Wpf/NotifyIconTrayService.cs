using System.Drawing;
using Forms = System.Windows.Forms;
using MomentumHunter.Application;

namespace MomentumHunter.Desktop.Wpf;

public sealed class NotifyIconTrayService : ITrayService
{
    private Forms.NotifyIcon? _notifyIcon;
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
        if (_notifyIcon is not null)
        {
            return;
        }

        var menu = new Forms.ContextMenuStrip();
        var heading = new Forms.ToolStripMenuItem("Momentum Hunter") { Enabled = false };
        _statusItem = new Forms.ToolStripMenuItem("System: Starting") { Enabled = false };
        var openItem = new Forms.ToolStripMenuItem("Open Workstation");
        _pauseOrResumeItem = new Forms.ToolStripMenuItem("Pause Monitoring");
        _runScanNowItem = new Forms.ToolStripMenuItem("Run Scan Now");
        var systemStatusItem = new Forms.ToolStripMenuItem("View System Status");
        var exitItem = new Forms.ToolStripMenuItem("Exit Momentum Hunter");

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

        _notifyIcon = new Forms.NotifyIcon
        {
            ContextMenuStrip = menu,
            Icon = SystemIcons.Application,
            Text = "Momentum Hunter - Starting",
            Visible = true,
        };
        _notifyIcon.DoubleClick += (_, _) => OpenRequested?.Invoke(this, EventArgs.Empty);
    }

    public void UpdateStatus(BackgroundCollectionStatus status)
    {
        if (_notifyIcon is null || _statusItem is null || _pauseOrResumeItem is null || _runScanNowItem is null)
        {
            return;
        }

        _statusItem.Text = $"System: {status.State} - {status.Detail}";
        _pauseOrResumeItem.Text = status.State == BackgroundCollectionState.Paused ? "Resume Monitoring" : "Pause Monitoring";
        _pauseOrResumeItem.Enabled = status.State != BackgroundCollectionState.Stopping;
        _runScanNowItem.Enabled = status.State is not (BackgroundCollectionState.Paused or BackgroundCollectionState.Stopping or BackgroundCollectionState.Blocked);
        _notifyIcon.Text = CreateTooltip(status);
    }

    public void ShowNotification(string title, string message)
    {
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
        if (_notifyIcon is null)
        {
            return;
        }

        _notifyIcon.Visible = false;
        _notifyIcon.Dispose();
        _notifyIcon = null;
        _statusItem = null;
        _pauseOrResumeItem = null;
        _runScanNowItem = null;
    }

    private static string CreateTooltip(BackgroundCollectionStatus status)
    {
        var lastScan = status.LastCompletedCycleAt is { } completed ? completed.ToLocalTime().ToString("HH:mm") : "pending";
        var text = $"Momentum Hunter | {status.State} | {status.MonitoredSymbolCount} symbols | {lastScan}";
        return text.Length <= 63 ? text : text[..63];
    }
}
