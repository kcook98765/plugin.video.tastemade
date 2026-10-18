"""Render original geometric add-on art; build-time Pillow only, no input assets.

Run with the existing toolkit Python environment. Never downloads or opens an
image, font, programme still, trademark/logo or screenshot. Refuses overwrites.
"""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
MINT = (120, 220, 193)
CREAM = (240, 240, 224)
CORAL = (237, 163, 119)


def gradient(width, height, top, bottom):
    image = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(round(a + (b - a) * ratio) for a, b in zip(top, bottom))
        draw.line((0, y, width, y), fill=color)
    return image


def star(draw, x, y, size, color):
    draw.polygon([(x, y - size), (x + size * .24, y - size * .24),
                  (x + size, y), (x + size * .24, y + size * .24),
                  (x, y + size), (x - size * .24, y + size * .24),
                  (x - size, y), (x - size * .24, y - size * .24)], fill=color)


def icon():
    # Supersampling is rasterization of these original shapes, not a stock image.
    scale = 2
    image = gradient(512 * scale, 512 * scale, (18, 31, 46), (25, 63, 68))
    draw = ImageDraw.Draw(image)

    def box(values):
        return tuple(round(value * scale) for value in values)

    draw.rounded_rectangle(box((20, 20, 492, 492)), radius=48 * scale,
                           fill=(22, 43, 56), outline=(50, 78, 87), width=2 * scale)
    draw.ellipse(box((88, 88, 424, 424)), outline=MINT, width=15 * scale)
    draw.ellipse(box((111, 111, 401, 401)), outline=(69, 116, 117), width=3 * scale)
    draw.polygon([box((220, 178)), box((220, 334)), box((344, 256))], fill=CREAM)
    # Small fork and leaf accents communicate food without provider branding.
    draw.line(box((60, 189, 60, 333)), fill=CORAL, width=7 * scale)
    for x in (48, 60, 72):
        draw.line(box((x, 174, x, 217)), fill=CORAL, width=5 * scale)
    draw.arc(box((47, 198, 73, 232)), 0, 180, fill=CORAL, width=5 * scale)
    draw.polygon([box((358, 112)), box((367, 80)), box((411, 72)),
                  box((403, 106)), box((378, 126))], fill=MINT)
    draw.line(box((363, 121, 399, 84)), fill=(22, 43, 56), width=3 * scale)
    star(draw, 115 * scale, 414 * scale, 16 * scale, CORAL)
    return image.resize((512, 512), Image.Resampling.LANCZOS)


def fanart():
    image = gradient(1920, 1080, (13, 25, 40), (20, 47, 59)).convert('RGBA')
    layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    # Leave the left two-thirds subdued for Kodi's information text/panels.
    for radius, alpha in ((420, 8), (360, 12), (305, 24)):
        draw.ellipse((1490 - radius, 540 - radius, 1490 + radius, 540 + radius),
                     fill=(*MINT, alpha))
    draw.ellipse((1210, 260, 1770, 820), outline=(*MINT, 135), width=12)
    draw.ellipse((1242, 292, 1738, 788), outline=(*MINT, 55), width=3)
    draw.polygon([(1404, 406), (1404, 674), (1624, 540)], fill=(*CREAM, 170))
    # A dotted route, a home outline, a leaf and compass spark: original geometry.
    for i in range(17):
        t = i / 16
        x = 650 + 470 * t
        y = 900 - 610 * t + 90 * (1 - t) * t
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(*MINT, 35))
    draw.line([(1040, 266), (1110, 202), (1180, 266)], fill=(*CORAL, 80), width=5)
    draw.line([(1057, 253), (1057, 326), (1163, 326), (1163, 253)],
              fill=(*CORAL, 80), width=5)
    draw.line([(1093, 326), (1093, 284), (1127, 284), (1127, 326)],
              fill=(*CORAL, 65), width=4)
    draw.polygon([(1660, 914), (1669, 854), (1745, 826), (1734, 889),
                  (1693, 921)], fill=(*MINT, 80))
    draw.line([(1669, 912), (1729, 844)], fill=(13, 25, 40, 120), width=4)
    star(draw, 1770, 154, 37, (*CORAL, 140))
    for x, y, radius in ((930, 160, 5), (1720, 948, 4), (1840, 712, 3)):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*CREAM, 75))
    return Image.alpha_composite(image, layer).convert('RGB')


def main():
    destinations = {'resources/icon.png': icon, 'resources/fanart.jpg': fanart}
    if any((ROOT / name).exists() for name in destinations):
        raise SystemExit('Artwork exists; refusing to overwrite reviewed source assets.')
    result = {}
    for name, render in destinations.items():
        path = ROOT / name
        if not path.parent.is_dir():
            raise SystemExit('Expected resources directory is absent.')
        image = render()
        with path.open('xb') as stream:
            if path.suffix == '.png':
                image.save(stream, format='PNG', optimize=True)
            else:
                image.save(stream, format='JPEG', quality=90, optimize=True, subsampling=0)
        result[name] = {'dimensions': list(image.size), 'mode': image.mode,
                        'bytes': path.stat().st_size,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
