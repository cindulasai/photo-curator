from __future__ import annotations
import imagehash
import numpy as np
from PIL import Image


def phash64(img: Image.Image) -> int:
    return int(str(imagehash.phash(img)), 16)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def find_pairs(hashes: list[tuple[str, int]], max_dist: int) -> list[tuple[str, str, int]]:
    if len(hashes) < 2:
        return []
    names = [n for n, _ in hashes]
    arr = np.array([[(h >> s) & 0xFF for s in range(56, -8, -8)] for _, h in hashes],
                   dtype=np.uint8)
    bits = np.unpackbits(arr, axis=1)                       # (n, 64)
    out = []
    chunk = 512
    for i0 in range(0, len(hashes), chunk):
        block = bits[i0:i0 + chunk]
        dists = (block[:, None, :] != bits[None, :, :]).sum(axis=2)
        for bi in range(block.shape[0]):
            i = i0 + bi
            js = np.nonzero(dists[bi] <= max_dist)[0]
            for j in js:
                if j > i:
                    out.append((names[i], names[j], int(dists[bi][j])))
    return out


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def build_groups(photos: list[dict], cfg: dict) -> list[dict]:
    t = cfg["triage"]
    ts = {p["rel_path"]: p["ts"] for p in photos}
    hashes = sorted((p["rel_path"], p["stage2"]["phash"]) for p in photos)
    pairs = find_pairs(hashes, t["burst_hamming_max"])
    uf, burst_edges = _UF(), set()
    for a, b, d in pairs:
        is_burst = d <= t["burst_hamming_max"] and abs(ts[a] - ts[b]) <= t["burst_gap_s"]
        is_near = d <= t["neardupe_hamming_max"]
        if is_burst or is_near:
            uf.union(a, b)
            if is_burst:
                burst_edges.add((a, b))
    clusters: dict[str, list[str]] = {}
    for name, _ in hashes:
        if name in uf.p:
            clusters.setdefault(uf.find(name), []).append(name)
    groups = []
    for root in sorted(clusters):
        members = sorted(clusters[root])
        if len(members) < 2:
            continue
        mset = set(members)
        kind = "burst" if any(a in mset and b in mset for a, b in burst_edges) else "neardupe"
        groups.append({"kind": kind, "members": members})
    return groups
