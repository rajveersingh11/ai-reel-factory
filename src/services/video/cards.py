"""
Dynamic Scene Card & Statistic Card Generator
==============================================
Generates 1080x1920 high-resolution visual cards for scenes.
Provides:
  - Branded header (e.g. SKYON IT SOLUTIONS)
  - Hero metric / statistic display (e.g. "1.5 LAKH+", "40% COST CUT")
  - Topic / subtitle badge
  - Verified source citation tag (e.g. "Source: DPIIT 2024")
  - Safe zone awareness: keeps the lower half clean for subtitles
"""

from __future__ import annotations

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def _get_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load Segoe UI, Arial, or fallback font."""
    font_names = (
        ["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]
    )
    for name in font_names:
        font_path = os.path.join(r"C:\Windows\Fonts", name)
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def create_gradient_canvas(width: int = 1080, height: int = 1920, top_color=(10, 20, 38), bottom_color=(3, 7, 18)) -> Image.Image:
    """Create a smooth vertical gradient image."""
    base = Image.new("RGBA", (width, height), top_color)
    top_r, top_g, top_b = top_color
    bot_r, bot_g, bot_b = bottom_color

    # Draw vertical linear gradient
    draw = ImageDraw.Draw(base)
    for y in range(height):
        factor = y / height
        r = int(top_r + (bot_r - top_r) * factor)
        g = int(top_g + (bot_g - top_g) * factor)
        b = int(top_b + (bot_b - top_b) * factor)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    return base


def render_scene_card(
    scene_idx: int,
    total_scenes: int,
    brand_name: str,
    category_tag: str,
    metric_text: str,
    metric_label: str,
    source_citation: str | None = None,
    output_path: Path | None = None,
) -> Image.Image:
    """
    Renders a vertical 1080x1920 card tailored for short-form video.
    Upper region: Branding & Hero Stat Card.
    Lower region: Reserved safe zone for burned-in captions.
    """
    canvas = create_gradient_canvas(1080, 1920, top_color=(13, 27, 42), bottom_color=(5, 10, 18))
    draw = ImageDraw.Draw(canvas)

    # 1. Top Brand Header (Y: 120-220)
    font_brand = _get_font(34, bold=True)
    font_cat = _get_font(26, bold=False)

    brand_text = brand_name.upper()
    cat_text = category_tag.upper()
    header_str = f"{brand_text}  •  {cat_text}"
    draw.text((80, 140), header_str, font=font_brand, fill=(0, 212, 255, 240))

    # Scene step pills (dots/progress at top right)
    pill_text = f"SCENE {scene_idx + 1}/{total_scenes}"
    font_pill = _get_font(24, bold=True)
    draw.text((860, 146), pill_text, font=font_pill, fill=(160, 175, 200, 200))

    # Divider line
    draw.line([(80, 200), (1000, 200)], fill=(40, 70, 110, 180), width=2)

    # 2. Main Stat Card Container (Y: 320-950)
    card_box = [(70, 320), (1010, 960)]
    # Rounded card background
    draw.rounded_rectangle(card_box, radius=32, fill=(20, 35, 60, 220), outline=(0, 180, 255, 140), width=3)

    # Card Accent Tag
    tag_box = [(110, 360), (380, 420)]
    draw.rounded_rectangle(tag_box, radius=14, fill=(0, 180, 255, 40), outline=(0, 200, 255, 200), width=2)
    font_tag = _get_font(26, bold=True)
    draw.text((130, 372), "STARTUP INSIGHT", font=font_tag, fill=(0, 225, 255, 255))

    # Hero Metric (e.g. "1.5 LAKH+", "40% COST CUT")
    font_hero = _get_font(88, bold=True)
    draw.text((110, 470), metric_text, font=font_hero, fill=(255, 255, 255, 255))

    # Metric Label / Context
    font_label = _get_font(42, bold=False)
    draw.text((110, 610), metric_label, font=font_label, fill=(185, 205, 230, 255))

    # Verified Source Citation Tag (Requirement 4.C Fact-Checking badge)
    if source_citation:
        badge_box = [(110, 840), (970, 910)]
        draw.rounded_rectangle(badge_box, radius=12, fill=(15, 28, 48, 255), outline=(60, 100, 150, 180), width=1)
        font_source = _get_font(24, bold=False)
        badge_text = f"✓ Verified Source: {source_citation}"
        draw.text((130, 860), badge_text, font=font_source, fill=(100, 220, 140, 240))

    # 3. Middle Visual Accent (Separator before subtitles zone)
    draw.line([(100, 1060), (980, 1060)], fill=(30, 50, 80, 100), width=1)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, "PNG")

    return canvas

