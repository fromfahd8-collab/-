"""
KSO Download Turbo Ultra V1.0
Generates the application icon (app_icon.ico).
Run this once before starting main.py:
    python generate_assets.py
"""
from PIL import Image, ImageDraw, ImageFont
import os


def create_app_icon():
    size = 256
    img = Image.new("RGBA", (size, size), (0, 120, 215, 255))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("arialbd.ttf", 90)
    except Exception:
        font = ImageFont.load_default()

    # Draw "KSO" text
    text = "KSO"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (size - text_w) // 2 - bbox[0]
    text_y = (size - text_h) // 2 - bbox[1] - 20
    draw.text((text_x, text_y), text, fill="white", font=font)

    # Download arrow glued right under the "K" (first letter), pointing down
    k_left_x = text_x
    arrow_top_y = text_y + text_h + 6
    arrow_cx = k_left_x + 22

    # Vertical stem of the arrow
    draw.rectangle(
        [arrow_cx - 6, arrow_top_y, arrow_cx + 6, arrow_top_y + 26],
        fill="white",
    )
    # Arrow head (triangle) pointing down, right under the stem
    draw.polygon(
        [
            (arrow_cx - 18, arrow_top_y + 22),
            (arrow_cx + 18, arrow_top_y + 22),
            (arrow_cx, arrow_top_y + 48),
        ],
        fill="white",
    )

    img.save("app_icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("app_icon.ico created successfully.")


if __name__ == "__main__":
    create_app_icon()
