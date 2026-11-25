"""Render the Spine viewer app icon (dark plate + vertebrae + play triangle).

Design: near-black navy rounded square, a vertical column of three white
vertebra blocks joined by thin stems, and a coral play triangle to its right.
Every target size is drawn independently at 8x supersampling, with adaptive
minimum stroke widths, so 16x16 stays legible instead of blurring into mush.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"

SUPERSAMPLE = 8
SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]

PLATE = (20, 27, 42, 255)      # #141B2A
BONE = (255, 255, 255, 255)
PLAY = (255, 122, 77, 255)     # #FF7A4D

PAD = 0.045                    # outer breathing room, per side


def rounded_triangle(vertices, radius, steps=28):
    """Polygon points for a triangle whose corners are rounded."""
    pts = []
    for i, v in enumerate(vertices):
        prev_v = vertices[i - 1]
        next_v = vertices[(i + 1) % len(vertices)]
        v0 = (prev_v[0] - v[0], prev_v[1] - v[1])
        v1 = (next_v[0] - v[0], next_v[1] - v[1])
        l0 = math.hypot(*v0)
        l1 = math.hypot(*v1)
        r = min(radius, l0 * 0.45, l1 * 0.45)
        p0 = (v[0] + v0[0] / l0 * r, v[1] + v0[1] / l0 * r)
        p1 = (v[0] + v1[0] / l1 * r, v[1] + v1[1] / l1 * r)
        pts.append(p0)
        for s in range(1, steps + 1):
            t = s / steps
            x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * v[0] + t ** 2 * p1[0]
            y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * v[1] + t ** 2 * p1[1]
            pts.append((x, y))
    return pts


def vertebra_block(w: int, h: int, angle: float, fill) -> Image.Image:
    """A rounded-rect vertebra, rotated and returned with a transparent pad."""
    pad = max(4, int(h * 0.25))
    block = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(block).rounded_rectangle(
        (pad, pad, pad + w - 1, pad + h - 1),
        radius=int(min(w, h) * 0.42),
        fill=fill,
    )
    return block.rotate(angle, resample=Image.BICUBIC, expand=True)


def draw_icon(px_size: int) -> Image.Image:
    size = px_size * SUPERSAMPLE
    inset = int(size * PAD)
    box = (inset, inset, size - inset, size - inset)
    span = size - 2 * inset

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # ---- plate -------------------------------------------------------
    plate = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle(box, radius=int(span * 0.23), fill=PLATE)
    canvas.alpha_composite(plate)

    tiny = px_size <= 24
    # ---- spine -------------------------------------------------------
    # small sizes get wider, flatter bones so they read as blocks, not dots
    bw = int(span * (0.170 if tiny else 0.158))
    bh = int(span * (0.132 if tiny else 0.118))
    stem = int(max(span * 0.024, SUPERSAMPLE * 1.0))
    x_left = box[0] + span * (0.315 if tiny else 0.320)
    ys = (0.272, 0.5, 0.728)
    xs = (x_left, x_left + span * 0.020, x_left)
    centers = [(xs[i], box[1] + span * ys[i]) for i in range(3)]

    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(layer)
    for a, b in zip(centers, centers[1:]):
        sd.line([a, b], fill=BONE, width=stem)
    for cx, cy in centers:
        blk = vertebra_block(bw, bh, -12.0, BONE)
        layer.alpha_composite(
            blk, (int(cx - blk.width / 2), int(cy - blk.height / 2))
        )

    # ---- play triangle -----------------------------------------------
    tri_h = span * (0.500 if tiny else 0.465)
    tri_w = span * (0.330 if tiny else 0.300)
    left = box[0] + span * (0.470 if tiny else 0.475)
    cy = box[1] + span * 0.5
    verts = [
        (left, cy - tri_h / 2),
        (left + tri_w, cy),
        (left, cy + tri_h / 2),
    ]
    ImageDraw.Draw(layer).polygon(
        rounded_triangle(verts, tri_h * 0.055), fill=PLAY
    )

    canvas.alpha_composite(layer)
    return canvas.resize((px_size, px_size), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)

    frames = {s: draw_icon(s) for s in SIZES}
    ico_path = ASSETS / "icon.ico"
    frames[256].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=[frames[s] for s in SIZES if s != 256],
    )
    draw_icon(512).save(ASSETS / "icon.png")

    # size proof sheet: real small sizes at 3x, on both light and dark ground
    cell = 4
    gap = 12
    blocks = [16, 24, 32, 48]
    width = gap + sum(s * cell + gap for s in blocks)
    sheet = Image.new("RGBA", (width, 2 * (48 * cell + 2 * gap)), (250, 250, 252, 255))
    ImageDraw.Draw(sheet).rectangle(
        (0, 48 * cell + 2 * gap, width, sheet.height), fill=(24, 28, 38, 255)
    )
    for row, top in enumerate((gap, 48 * cell + 2 * gap + gap)):
        x = gap
        for s in blocks:
            f = frames[s].resize((s * cell, s * cell), Image.NEAREST)
            sheet.alpha_composite(f, (x, top + (48 * cell - f.height) // 2))
            x += f.width + gap
    sheet.save(ASSETS / "icon-sizes.png")

    print(f"ico   -> {ico_path} ({ico_path.stat().st_size} bytes, {len(SIZES)} sizes)")
    print(f"png   -> {ASSETS / 'icon.png'}")
    print(f"sheet -> {ASSETS / 'icon-sizes.png'}")


if __name__ == "__main__":
    main()
