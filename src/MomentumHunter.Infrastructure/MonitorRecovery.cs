using MomentumHunter.Contracts;

namespace MomentumHunter.Infrastructure;

public static class MonitorRecovery
{
    public static PaneLayout Recover(PaneLayout layout, IReadOnlyList<DisplayGeometry> displays)
    {
        if (layout.FloatingBounds is null || displays.Count == 0)
        {
            return layout;
        }

        var display = displays.FirstOrDefault(item => item.DisplayKey == layout.DisplayKey) ?? displays[0];
        var workArea = display.WorkingArea;
        var bounds = layout.FloatingBounds;
        var width = Math.Clamp(bounds.Width, 480, workArea.Width);
        var height = Math.Clamp(bounds.Height, 320, workArea.Height);
        var x = Math.Clamp(bounds.X, workArea.X, workArea.Right - width);
        var y = Math.Clamp(bounds.Y, workArea.Y, workArea.Bottom - height);
        return layout with
        {
            DisplayKey = display.DisplayKey,
            FloatingBounds = new RectGeometry(x, y, width, height),
        };
    }
}
