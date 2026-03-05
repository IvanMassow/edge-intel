"""Generate OG images for Retail Gazette, Retail Marketing, and Retail Packaging."""
from PIL import Image, ImageDraw
import os

ASSETS = os.path.dirname(os.path.abspath(__file__))
OG_W, OG_H = 1200, 630

configs = [
    {
        "name": "og-gazette.png",
        "logo": os.path.join(ASSETS, "new-logo-gazette.png"),
        # Deep charcoal-black with subtle warmth
        "bg_top": (17, 17, 17),
        "bg_bottom": (30, 28, 26),
        "accent": (255, 255, 255),  # white accent line
    },
    {
        "name": "og-marketing.png",
        "logo": os.path.join(ASSETS, "new-logo-marketing.png"),
        # Dark burgundy
        "bg_top": (58, 12, 12),
        "bg_bottom": (30, 8, 8),
        "accent": (176, 34, 52),  # warm red accent
    },
    {
        "name": "og-packaging.png",
        "logo": os.path.join(ASSETS, "new-logo-packaging.png"),
        # Deep wine/burgundy
        "bg_top": (48, 16, 16),
        "bg_bottom": (26, 10, 10),
        "accent": (148, 59, 59),  # terracotta accent
    },
]

for cfg in configs:
    # Create gradient background
    img = Image.new("RGB", (OG_W, OG_H))
    draw = ImageDraw.Draw(img)
    for y in range(OG_H):
        ratio = y / OG_H
        r = int(cfg["bg_top"][0] * (1 - ratio) + cfg["bg_bottom"][0] * ratio)
        g = int(cfg["bg_top"][1] * (1 - ratio) + cfg["bg_bottom"][1] * ratio)
        b = int(cfg["bg_top"][2] * (1 - ratio) + cfg["bg_bottom"][2] * ratio)
        draw.line([(0, y), (OG_W, y)], fill=(r, g, b))

    # Draw thin accent line across top (3px)
    ac = cfg["accent"]
    for y in range(3):
        draw.line([(0, y), (OG_W, y)], fill=ac)

    # Draw thin accent line across bottom (3px)
    for y in range(OG_H - 3, OG_H):
        draw.line([(0, y), (OG_W, y)], fill=ac)

    # Load and place logo (white version needed — invert dark pixels)
    logo = Image.open(cfg["logo"]).convert("RGBA")

    # Make logo white: for each pixel, keep alpha but set RGB to white
    pixels = logo.load()
    for x in range(logo.width):
        for y in range(logo.height):
            r, g, b, a = pixels[x, y]
            if a > 0:
                pixels[x, y] = (255, 255, 255, a)

    # Scale logo to fit nicely (max width 600px, maintain aspect)
    max_logo_w = 600
    scale = max_logo_w / logo.width
    new_w = int(logo.width * scale)
    new_h = int(logo.height * scale)
    logo = logo.resize((new_w, new_h), Image.LANCZOS)

    # Center logo
    x_offset = (OG_W - new_w) // 2
    y_offset = (OG_H - new_h) // 2

    # Paste with alpha mask
    img.paste(logo, (x_offset, y_offset), logo)

    # Save
    out_path = os.path.join(ASSETS, cfg["name"])
    img.save(out_path, "PNG", optimize=True)
    print(f"Created {cfg['name']} ({OG_W}x{OG_H})")

print("Done!")
