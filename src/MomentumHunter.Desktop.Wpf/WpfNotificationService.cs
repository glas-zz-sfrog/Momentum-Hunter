using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using MomentumHunter.Application;

namespace MomentumHunter.Desktop.Wpf;

public sealed class WpfNotificationService : INotificationService
{
    public Task ShowFirstCloseNoticeAsync(Func<bool, Task> dismissed, CancellationToken cancellationToken = default)
    {
        var notice = new FirstCloseNoticeWindow(dismissed);
        notice.Show();
        return Task.CompletedTask;
    }

    private sealed class FirstCloseNoticeWindow : Window
    {
        private readonly Func<bool, Task> _dismissed;
        private readonly System.Windows.Controls.CheckBox _doNotShowAgain;
        private bool _reported;

        public FirstCloseNoticeWindow(Func<bool, Task> dismissed)
        {
            _dismissed = dismissed;
            Title = "Momentum Hunter";
            Width = 390;
            Height = 190;
            ResizeMode = ResizeMode.NoResize;
            ShowInTaskbar = false;
            WindowStartupLocation = WindowStartupLocation.Manual;
            Left = Math.Max(SystemParameters.WorkArea.Left + 16, SystemParameters.WorkArea.Right - Width - 16);
            Top = Math.Max(SystemParameters.WorkArea.Top + 16, SystemParameters.WorkArea.Bottom - Height - 16);
            Background = new SolidColorBrush(Color.FromRgb(27, 39, 49));
            Foreground = new SolidColorBrush(Color.FromRgb(231, 237, 242));

            var root = new StackPanel { Margin = new Thickness(18) };
            root.Children.Add(new TextBlock
            {
                Text = "Momentum Hunter is still running and collecting data.",
                FontFamily = new FontFamily("Segoe UI"),
                FontWeight = FontWeights.SemiBold,
                TextWrapping = TextWrapping.Wrap,
            });
            root.Children.Add(new TextBlock
            {
                Text = "Use the system tray icon to reopen it or exit completely.",
                FontFamily = new FontFamily("Segoe UI"),
                Foreground = new SolidColorBrush(Color.FromRgb(153, 169, 183)),
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 7, 0, 12),
            });
            _doNotShowAgain = new System.Windows.Controls.CheckBox
            {
                Content = "Do not show this again",
                FontFamily = new FontFamily("Segoe UI"),
                Foreground = Foreground,
                Margin = new Thickness(0, 0, 0, 12),
            };
            root.Children.Add(_doNotShowAgain);
            var continueButton = new Button
            {
                Content = "Continue",
                HorizontalAlignment = HorizontalAlignment.Right,
                Padding = new Thickness(14, 5, 14, 5),
            };
            continueButton.Click += (_, _) => Close();
            root.Children.Add(continueButton);
            Content = root;
            Closed += async (_, _) => await ReportDismissalAsync();
        }

        private async Task ReportDismissalAsync()
        {
            if (_reported)
            {
                return;
            }

            _reported = true;
            await _dismissed(_doNotShowAgain.IsChecked == true);
        }
    }
}

public sealed class ExitConfirmationWindow : Window
{
    private ExitConfirmationWindow()
    {
        Title = "Exit Momentum Hunter";
        Width = 430;
        Height = 190;
        ResizeMode = ResizeMode.NoResize;
        ShowInTaskbar = false;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        Background = new SolidColorBrush(Color.FromRgb(27, 39, 49));
        Foreground = new SolidColorBrush(Color.FromRgb(231, 237, 242));

        var root = new StackPanel { Margin = new Thickness(18) };
        root.Children.Add(new TextBlock
        {
            Text = "Exit Momentum Hunter and stop background collection?",
            FontFamily = new FontFamily("Segoe UI"),
            FontWeight = FontWeights.SemiBold,
            TextWrapping = TextWrapping.Wrap,
        });
        root.Children.Add(new TextBlock
        {
            Text = "Closing the workstation normally keeps in-process monitoring active in the system tray.",
            FontFamily = new FontFamily("Segoe UI"),
            Foreground = new SolidColorBrush(Color.FromRgb(153, 169, 183)),
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 7, 0, 14),
        });
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
        var cancel = new Button { Content = "Cancel", Padding = new Thickness(14, 5, 14, 5), Margin = new Thickness(0, 0, 8, 0) };
        cancel.Click += (_, _) => DialogResult = false;
        var exit = new Button { Content = "Exit and Stop Collection", Padding = new Thickness(14, 5, 14, 5) };
        exit.Click += (_, _) => DialogResult = true;
        buttons.Children.Add(cancel);
        buttons.Children.Add(exit);
        root.Children.Add(buttons);
        Content = root;
    }

    public static bool Confirm() => new ExitConfirmationWindow().ShowDialog() == true;
}
