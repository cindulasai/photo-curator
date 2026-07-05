from __future__ import annotations
import json
from importlib.resources import files
import cv2
import numpy as np
from PIL import Image

_DEVICE_RES = {tuple(p) for p in json.loads(
    files("curator").joinpath("data/device_resolutions.json").read_text())}
_CASCADE = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def to_gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"))


def blur_scores(gray: np.ndarray) -> tuple[float, float]:
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    h, w = gray.shape
    ch, cw = h // 4, w // 4
    center = lap[ch:h - ch, cw:w - cw]
    return float(lap.var()), float(center.var())


def exposure_stats(gray: np.ndarray) -> tuple[float, float]:
    n = gray.size
    return (float((gray < 8).sum()) * 100.0 / n,
            float((gray > 247).sum()) * 100.0 / n)


def doc_stats(gray: np.ndarray) -> tuple[float, float]:
    white_ratio = float((gray > 200).sum()) / gray.size
    edges = cv2.Canny(gray, 50, 150)
    return white_ratio, float((edges > 0).sum()) / gray.size


def face_count(gray: np.ndarray) -> int:
    h, w = gray.shape
    scale = 512 / max(h, w)
    if scale < 1:
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)))
    faces = _CASCADE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6,
                                      minSize=(40, 40))
    return len(faces)


def is_screenshot_candidate(width: int, height: int, exif_make, fmt: str) -> bool:
    if exif_make:
        return False
    return (width, height) in _DEVICE_RES or (height, width) in _DEVICE_RES \
        or fmt.upper() == "PNG"


def sharpness(stage2: dict) -> float:
    return max(stage2.get("lap_var_global", 0.0), stage2.get("lap_var_center", 0.0))
