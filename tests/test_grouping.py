from PIL import Image
from curator.config import load_config
from curator.grouping import phash64, hamming, find_pairs, build_groups
from tests.conftest import make_image

def test_phash_similar_vs_different(tmp_path):
    a = phash64(Image.open(make_image(tmp_path / "a.jpg", "scene", seed=1)))
    a2 = phash64(Image.open(make_image(tmp_path / "a2.jpg", "scene", seed=1, blur=2)))
    b = phash64(Image.open(make_image(tmp_path / "b.jpg", "scene", seed=99)))
    assert hamming(a, a2) <= 6
    assert hamming(a, b) > 10

def test_find_pairs_matches_bruteforce():
    import random
    rng = random.Random(0)
    hashes = [(f"p{i:03d}.jpg", rng.getrandbits(64)) for i in range(80)]
    hashes.append(("p900.jpg", hashes[0][1] ^ 0b111))          # dist 3 from p000
    hashes = sorted(hashes)
    got = set((a, b) for a, b, _ in find_pairs(hashes, 6))
    brute = set()
    for i in range(len(hashes)):
        for j in range(i + 1, len(hashes)):
            na, ha = hashes[i]
            nb, hb = hashes[j]
            if hamming(ha, hb) <= 6:
                brute.add((min(na, nb), max(na, nb)))
    assert got == brute and ("p000.jpg", "p900.jpg") in got

def test_build_groups_burst_vs_neardupe():
    h = 0xABCDEF1234567890
    photos = [
        {"rel_path": "a1.jpg", "ts": 100.0, "stage2": {"phash": h}},
        {"rel_path": "a2.jpg", "ts": 101.5, "stage2": {"phash": h ^ 0b11}},        # burst w/ a1
        {"rel_path": "far.jpg", "ts": 99999.0, "stage2": {"phash": h ^ 0b1}},      # neardupe (time far)
        {"rel_path": "solo.jpg", "ts": 100.0, "stage2": {"phash": h ^ (2**63 - 1)}},
    ]
    groups = build_groups(photos, load_config(None))
    assert len(groups) == 1                       # all three phash-close ones merge
    g = groups[0]
    assert g["kind"] == "burst" and g["members"] == ["a1.jpg", "a2.jpg", "far.jpg"]
