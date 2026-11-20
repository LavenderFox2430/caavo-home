"""Render the original project icon from simple vector primitives (optional Pillow)."""

from pathlib import Path

from PIL import Image, ImageDraw

DESTINATION = Path(__file__).resolve().parents[1] / "custom_components/caavo_home/brand"


def main() -> None:
    scale = 4
    canvas = Image.new("RGBA", (256 * scale, 256 * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    def points(values):
        return [tuple(int(v * scale) for v in pair) for pair in values]

    draw.rounded_rectangle(
        (8 * scale, 8 * scale, 248 * scale, 248 * scale), radius=52 * scale, fill="#163248"
    )
    draw.rounded_rectangle(
        (48 * scale, 54 * scale, 208 * scale, 166 * scale),
        radius=15 * scale,
        outline="#EAF7FF",
        width=10 * scale,
    )
    draw.line(points([(103, 188), (153, 188)]), fill="#EAF7FF", width=10 * scale)
    draw.line(points([(128, 168), (128, 188)]), fill="#EAF7FF", width=10 * scale)
    draw.line(points([(83, 111), (162, 111)]), fill="#53D7C6", width=13 * scale)
    draw.polygon(points([(144, 88), (172, 111), (144, 134)]), fill="#53D7C6")
    for x in (88, 114, 140, 166):
        draw.ellipse(((x - 5) * scale, 211 * scale, (x + 5) * scale, 221 * scale), fill="#53D7C6")
    DESTINATION.mkdir(parents=True, exist_ok=True)
    canvas.resize((256, 256), Image.Resampling.LANCZOS).save(DESTINATION / "icon.png")
    canvas.resize((512, 512), Image.Resampling.LANCZOS).save(DESTINATION / "icon@2x.png")


if __name__ == "__main__":
    main()
