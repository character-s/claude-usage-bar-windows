"""System tray icon rendering - shows percentage text."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

ICON_SIZE = 256


def _color_for_pct(pct: float) -> tuple:
    """Match ui_window.py color scheme."""
    if pct < 0.50:
        return (52, 211, 153, 255)   # green  #34d399
    elif pct < 0.75:
        return (251, 191, 36, 255)   # yellow #fbbf24
    elif pct < 0.90:
        return (251, 146, 60, 255)   # orange #fb923c
    else:
        return (244, 63, 94, 255)    # red    #f43f5e


def render_icon(pct_5h: float, pct_7d: float, show_mode: str = "5h") -> Image.Image:
    """Render tray icon showing percentage text.

    show_mode: "5h" or "7d" - which value to display.
    """
    pct = pct_5h if show_mode == "5h" else pct_7d
    pct_int = int(round(pct * 100))
    text = str(pct_int)
    color = _color_for_pct(pct)

    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Maximize font size within icon
    if pct_int >= 100:
        font_size = 120
    else:
        font_size = 160

    try:
        font = ImageFont.truetype("segoeuib.ttf", font_size)  # Segoe UI Bold
    except OSError:
        try:
            font = ImageFont.truetype("consola.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()

    # Center text
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (ICON_SIZE - tw) // 2
    y = (ICON_SIZE - th) // 2 - bbox[1]

    draw.text((x, y), text, fill=color, font=font)

    return img


def render_unauthenticated_icon() -> Image.Image:
    """Render a tray icon showing '--' when not signed in."""
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("segoeuib.ttf", 80)
    except OSError:
        try:
            font = ImageFont.truetype("consola.ttf", 80)
        except OSError:
            font = ImageFont.load_default()

    text = "--"
    color = (120, 120, 140, 200)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (ICON_SIZE - tw) // 2
    y = (ICON_SIZE - th) // 2 - bbox[1]

    draw.text((x, y), text, fill=color, font=font)

    return img
