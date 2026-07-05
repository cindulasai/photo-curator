from __future__ import annotations
import random
from pathlib import Path
import pytest
from PIL import Image, ImageDraw, ImageFilter


def _paint_scene(d: ImageDraw.ImageDraw, w: int, h: int, rng: random.Random):
    for _ in range(300):  # high-frequency detail so Laplacian variance is high
        x, y = rng.randrange(w), rng.randrange(h)
        r = rng.randrange(4, 40)
        color = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
        d.ellipse([x, y, x + r, y + r], fill=color, outline=(0, 0, 0))
    for _ in range(60):
        x1, y1 = rng.randrange(w), rng.randrange(h)
        d.line([x1, y1, rng.randrange(w), rng.randrange(h)], fill=(0, 0, 0), width=2)


def make_image(path: Path, kind: str = "scene", *, size=(1600, 1200), exif_dt=None,
               exif_make="TestCam", gps=None, blur=0, brightness=1.0, seed=7) -> Path:
    rng = random.Random(seed)
    if kind == "screenshot":
        size = (1170, 2532)  # iPhone 13 resolution, in device_resolutions.json
        img = Image.new("RGB", size, (250, 250, 250))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, size[0], 90], fill=(20, 20, 20))          # status bar
        for i in range(8):                                            # UI rows
            d.rectangle([40, 200 + i * 260, size[0] - 40, 200 + i * 260 + 200],
                        outline=(180, 180, 180), fill=(235, 235, 240))
        exif_make = None
    elif kind == "black":
        img = Image.new("RGB", size, (2, 2, 2))
    elif kind == "white_doc":
        img = Image.new("RGB", size, (252, 252, 252))
        d = ImageDraw.Draw(img)
        for i in range(40):                                           # text-like lines
            y = 30 + i * (size[1] // 42)
            d.rectangle([50, y, size[0] - rng.randrange(60, 400), y + 8], fill=(30, 30, 30))
    else:
        img = Image.new("RGB", size, (120, 160, 200))
        d = ImageDraw.Draw(img)
        _paint_scene(d, *size, rng)
        if kind == "portrait":
            cx, cy = size[0] // 2, size[1] // 2
            d.ellipse([cx - 220, cy - 300, cx + 220, cy + 300], fill=(224, 172, 105))
            d.ellipse([cx - 90, cy - 120, cx - 30, cy - 60], fill=(255, 255, 255))
            d.ellipse([cx + 30, cy - 120, cx + 90, cy - 60], fill=(255, 255, 255))
            d.ellipse([cx - 75, cy - 105, cx - 45, cy - 75], fill=(40, 30, 20))
            d.ellipse([cx + 45, cy - 105, cx + 75, cy - 75], fill=(40, 30, 20))
            d.arc([cx - 80, cy + 80, cx + 80, cy + 200], 20, 160, fill=(120, 60, 50), width=8)
    if brightness != 1.0:
        img = img.point(lambda p: min(255, int(p * brightness)))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    exif = Image.Exif()
    if exif_make:
        exif[271] = exif_make                       # Make
    if exif_dt:
        exif[36867] = exif_dt                       # DateTimeOriginal "YYYY:MM:DD HH:MM:SS"
    kwargs = {"exif": exif.tobytes()} if (exif_make or exif_dt) else {}
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = "PNG" if kind == "screenshot" else "JPEG"
    img.save(path, fmt, **kwargs)
    if gps:
        _write_gps(path, gps)
    return path


def _write_gps(path: Path, latlon):
    from PIL import Image as I
    from PIL.TiffImagePlugin import IFDRational
    img = I.open(path)
    exif = img.getexif()
    lat, lon = latlon
    def dms(v):
        v = abs(v); d = int(v); m = int((v - d) * 60); s = ((v - d) * 60 - m) * 60
        return (IFDRational(d, 1), IFDRational(m, 1),
                IFDRational(round(s * 100), 100))
    gps = exif.get_ifd(34853)
    gps[1] = "N" if lat >= 0 else "S"
    gps[2] = dms(lat)
    gps[3] = "E" if lon >= 0 else "W"
    gps[4] = dms(lon)
    img.save(path, exif=exif)


@pytest.fixture
def img_factory():
    return make_image


def test_factory_smoke(tmp_path):
    p = make_image(tmp_path / "s.jpg", "scene", exif_dt="2026:05:12 10:00:00")
    assert p.exists()
    from PIL import Image as I
    assert I.open(p).getexif()[36867] == "2026:05:12 10:00:00"
