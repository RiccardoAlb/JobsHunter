"""Genera branding/JobsHunter.ico (Windows) e branding/JobsHunter.png (Linux, 512 px) dal logo originale.

Uso: python branding/make_icons.py [OFFSET]   (OFFSET come in make_favicon.py, default 45)
Richiede solo Pillow e funziona su ogni sistema (a differenza di make_icns.py, che usa iconutil di macOS).
"""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_favicon as mf  # noqa: E402
from make_icns import tile  # noqa: E402

HERE = Path(__file__).resolve().parent
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main(offset: int = 45) -> tuple[Path, Path]:
    crop = mf.make_crop(Image.open(HERE / "logo-original.jpg").convert("RGB"), offset)
    png = HERE / "JobsHunter.png"
    tile(crop, 512).save(png)
    ico = HERE / "JobsHunter.ico"
    tile(crop, 256).save(ico, format="ICO", sizes=ICO_SIZES)
    return ico, png


if __name__ == "__main__":
    print("create", *main(int(sys.argv[1]) if len(sys.argv) > 1 else 45))
