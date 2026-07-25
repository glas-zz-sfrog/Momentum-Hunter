"""Generate the Momentum Hunter application icon and Windows ICO frames."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ASSET_DIR = Path(__file__).resolve().parent
PNG_PATH = ASSET_DIR / "MomentumHunterIcon.png"
ICO_PATH = ASSET_DIR / "MomentumHunter.ico"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

NAVY = "#071a2f"
NAVY_EDGE = "#173b5d"
WHITE = "#f4f8fb"
TEAL = "#18d4c3"


def _scaled_point(point: tuple[float, float], scale: float) -> tuple[int, int]:
    return round(point[0] * scale), round(point[1] * scale)


def _render_icon(size: int) -> Image.Image:
    supersample = 8 if size <= 64 else 4
    canvas_size = size * supersample
    scale = canvas_size / 1024
    image = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    inset = round(32 * scale)
    radius = round(205 * scale)
    border_width = max(1, round(20 * scale))
    draw.rounded_rectangle(
        (inset, inset, canvas_size - inset - 1, canvas_size - inset - 1),
        radius=radius,
        fill=NAVY,
        outline=NAVY_EDGE,
        width=border_width,
    )

    stroke_width = max(2, round(116 * scale))
    white_path = [
        _scaled_point((210, 720), scale),
        _scaled_point((210, 350), scale),
        _scaled_point((390, 565), scale),
        _scaled_point((530, 405), scale),
        _scaled_point((640, 535), scale),
    ]
    draw.line(white_path, fill=WHITE, width=stroke_width, joint="curve")

    arrow_start = _scaled_point((620, 555), scale)
    arrow_tip = _scaled_point((820, 315), scale)
    draw.line((arrow_start, arrow_tip), fill=TEAL, width=stroke_width)

    arrow_head = [
        _scaled_point((816, 244), scale),
        _scaled_point((850, 350), scale),
        _scaled_point((743, 329), scale),
    ]
    draw.polygon(arrow_head, fill=TEAL)

    if supersample > 1:
        image = image.resize((size, size), Image.Resampling.LANCZOS)
    return image


def main() -> None:
    master = _render_icon(1024)
    master.save(PNG_PATH, "PNG", optimize=True)

    frames = [_render_icon(size) for size in ICON_SIZES]
    frames[-1].save(
        ICO_PATH,
        format="ICO",
        append_images=frames[:-1],
        sizes=[(size, size) for size in ICON_SIZES],
        bitmap_format="png",
    )


if __name__ == "__main__":
    main()
