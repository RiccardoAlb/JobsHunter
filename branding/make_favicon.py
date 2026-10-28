"""Rigenera le icone della GUI da branding/logo-original.jpg.

Uso: .venv/bin/python branding/make_favicon.py [OFFSET]
OFFSET = px (sull'originale 1024) di cui spostare il logo VERSO IL BASSO dentro l'icona.
0 = centrato sul riquadro geometrico, valori positivi lo abbassano.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "jobshunter" / "gui" / "static"
GLYPH = (270, 270, 755, 750)  # estensione reale del glifo (J inclusa) nell'originale


def make_crop(im, offset: int):
    x0, y0, x1, y1 = GLYPH
    side = int(max(x1 - x0, y1 - y0) * 1.34)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2 - offset  # finestra piu' in alto = logo piu' in basso
    return im.crop((cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2))


def rounded(img, size, radius=0.2):
    img = img.resize((size, size), Image.LANCZOS).convert("RGBA")
    m = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius=int(size * 4 * radius), fill=255)
    img.putalpha(m.resize((size, size), Image.LANCZOS))
    return img


def build(offset: int) -> None:
    crop = make_crop(Image.open(HERE / "logo-original.jpg").convert("RGB"), offset)
    for name, sz in (("favicon-32.png", 32), ("favicon-64.png", 64), ("apple-touch-icon.png", 180), ("logo-512.png", 512)):
        rounded(crop, sz).save(OUT / name)
    rounded(crop, 256).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])


if __name__ == "__main__":
    build(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
    print("icone rigenerate")
