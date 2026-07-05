from PIL import Image
from curator import metrics
from tests.conftest import make_image

def test_blur_separates_sharp_from_blurred(tmp_path):
    sharp = make_image(tmp_path / "s.jpg", "scene", seed=3)
    blurred = make_image(tmp_path / "b.jpg", "scene", blur=12, seed=3)
    gs = metrics.to_gray(Image.open(sharp)); gb = metrics.to_gray(Image.open(blurred))
    assert max(metrics.blur_scores(gs)) > 60
    assert max(metrics.blur_scores(gb)) < 25

def test_exposure_black_frame(tmp_path):
    black = make_image(tmp_path / "k.jpg", "black")
    pct_black, pct_white = metrics.exposure_stats(metrics.to_gray(Image.open(black)))
    assert pct_black > 85 and pct_white < 1

def test_doc_stats_flags_document(tmp_path):
    doc = make_image(tmp_path / "d.jpg", "white_doc")
    scene = make_image(tmp_path / "s.jpg", "scene", seed=4)
    wd, ed = metrics.doc_stats(metrics.to_gray(Image.open(doc)))
    ws, _ = metrics.doc_stats(metrics.to_gray(Image.open(scene)))
    assert wd >= 0.55 and ed >= 0.02 and ws < 0.55

def test_screenshot_candidate():
    assert metrics.is_screenshot_candidate(1170, 2532, None, "PNG")
    assert metrics.is_screenshot_candidate(2532, 1170, None, "JPEG")   # rotated match
    assert not metrics.is_screenshot_candidate(1170, 2532, "Apple", "JPEG")
    assert not metrics.is_screenshot_candidate(1601, 1201, None, "JPEG")

def test_face_count_zero_on_scene(tmp_path):
    scene = make_image(tmp_path / "s.jpg", "scene", seed=5)
    assert metrics.face_count(metrics.to_gray(Image.open(scene))) == 0
