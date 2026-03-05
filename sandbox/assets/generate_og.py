"""Generate OG images for Retail Gazette, Retail Marketing, and Retail Packaging.

Design: Premium cream/white background with centered logo, thin accent borders,
subtle dark strip at top and bottom for gravitas.
"""
from PIL import Image, ImageDraw
import os

ASSETS = os.path.dirname(os.path.abspath(__file__))
OG_W, OG_H = 1200, 630

configs = [
    {
        "name": "og-gazette.png",
        "logo": os.path.join(ASSETS, "new-logo-gazette.png"),
        "bg": (250, 249, 247),        # warm white
        "strip_color": (17, 17, 17),   # black strips
        "accent": (17, 17, 17),        # black accent line
        "strip_h": 60,
    },
    {
        "name": "og-marketing.png",
        "logo": os.path.join(ASSETS, "new-logo-marketing.png"),
        "bg": (253, 248, 247),         # very subtle warm pink-white
        "strip_color": (58, 12, 12),   # dark burgundy strips
        "accent": (139, 26, 26),       # burgundy accent line
        "strip_h": 60,
    },
    {
        "name": "og-packaging.png",
        "logo": os.path.join(ASSETS, "new-logo-packaging.png"),
        "bg": (249, 246, 244),         # warm neutral white
        "strip_color": (48, 16, 16),   # deep wine strips
        "accent": (122, 31, 31),       # packaging burgundy accent line
        "strip_h": 60,
    },
]

for cfg in configs:
    img = Image.new("RGB", (OG_W, OG_H), cfg["bg"])
    draw = ImageDraw.Draw(img)

    sh = cfg["strip_h"]
    sc = cfg["strip_color"]
    ac = cfg["accent"]

    # Top dark strip with subtle gradient
    for y in range(sh):
        ratio = y / sh
        r = int(sc[0] * (1 - ratio * 0.3))
        g = int(sc[1] * (1 - ratio * 0.3))
        b = int(sc[2] * (1 - ratio * 0.3))
        draw.line([(0, y), (OG_W, y)], fill=(r, g, b))

    # Bottom dark strip with subtle gradient
    for y in range(OG_H - sh, OG_H):
        ratio = (OG_H - y) / sh
        r = int(sc[0] * (1 - ratio * 0.3))
        g = int(sc[1] * (1 - ratio * 0.3))
        b = int(sc[2] * (1 - ratio * 0.3))
        draw.line([(0, y), (OG_W, y)], fill=(r, g, b))

    # Thin accent line at strip/content border (2px)
    draw.line([(0, sh), (OG_W, sh)], fill=ac, width=2)
    draw.line([(0, OG_H - sh - 1), (OG_W, OG_H - sh - 1)], fill=ac, width=2)

    # Load logo (original colors — designed for light backgrounds)
    logo = Image.open(cfg["logo"]).convert("RGBA")

    # Scale logo to fit within the content area (between strips)
    content_h = OG_H - 2 * sh
    max_logo_w = 620
    max_logo_h = content_h - 80  # padding

    scale_w = max_logo_w / logo.width
    scale_h = max_logo_h / logo.height
    scale = min(scale_w, scale_h)

    new_w = int(logo.width * scale)
    new_h = int(logo.height * scale)
    logo = logo.resize((new_w, new_h), Image.LANCZOS)

    # Center logo in the content area
    x_offset = (OG_W - new_w) // 2
    y_offset = sh + (content_h - new_h) // 2

    # Paste with alpha
    img.paste(logo, (x_offset, y_offset), logo)

    # Save
    out_path = os.path.join(ASSETS, cfg["name"])
    img.save(out_path, "PNG", optimize=True)
    print(f"Created {cfg['name']} ({OG_W}x{OG_H})")

print("Done!")
