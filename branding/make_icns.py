"""Genera branding/JobsHunter.icns (icona dell'app Mac) dal logo originale.

Uso: .venv/bin/python branding/make_icns.py [OFFSET]   (OFFSET come in make_favicon.py, default 45)
Richiede macOS (usa iconutil).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_favicon as mf  # noqa: E402

HERE = Path(__file__).resolve().parent
SIZES = {"icon_16x16": 16, "icon_16x16@2x": 32, "icon_32x32": 32, "icon_32x32@2x": 64,
         "icon_128x128": 128, "icon_128x128@2x": 256, "icon_256x256": 256, "icon_256x256@2x": 512,
         "icon_512x512": 512, "icon_512x512@2x": 1024}


def tile(crop: Image.Image, size: int) -> Image.Image:
    """Quadrato arrotondato con margine trasparente, come le icone macOS (Big Sur e successive)."""
    inner = int(size * 0.82)
    base = crop.resize((inner, inner), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (inner * 4, inner * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, inner * 4 - 1, inner * 4 - 1), radius=int(inner * 4 * 0.225), fill=255)
    base.putalpha(mask.resize((inner, inner), Image.LANCZOS))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(base, ((size - inner) // 2, (size - inner) // 2), base)
    return canvas


def main(offset: int = 45) -> Path:
    crop = mf.make_crop(Image.open(HERE / "logo-original.jpg").convert("RGB"), offset)
    out = HERE / "JobsHunter.icns"
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "JobsHunter.iconset"
        iconset.mkdir()
        for name, px in SIZES.items():
            tile(crop, px).save(iconset / f"{name}.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)
    return out


if __name__ == "__main__":
    print("creata", main(int(sys.argv[1]) if len(sys.argv) > 1 else 45))
