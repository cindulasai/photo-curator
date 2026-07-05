#!/usr/bin/env python3
"""Score a curated run against human labels (spec §11.2 bars).

answers.yaml schema:
  photos:
    "IMG_001.jpg": {verdict: keep, bucket: travel, burst_best: null}
    "IMG_002.jpg": {verdict: reject, bucket: null, burst_best: null}
    "IMG_010.jpg": {verdict: keep, bucket: people, burst_best: true}
"""
import json, sys
from pathlib import Path
import yaml

BARS = {"reject_precision": 0.95, "burst_agreement": 0.85,
        "bucket_accuracy": 0.80, "review_rate_max": 0.10}

def main(out_dir: str, answers_path: str) -> int:
    manifest = json.loads((Path(out_dir) / "manifest.json").read_text())
    labels = yaml.safe_load(Path(answers_path).read_text())["photos"]
    photos = {p["rel_path"]: p for p in manifest["photos"] if p["rel_path"] in labels}
    if not photos:
        print("no labeled photos found in manifest"); return 1

    rejected = [r for r, p in photos.items() if p["verdict"] == "reject"]
    true_rej = [r for r in rejected if labels[r]["verdict"] == "reject"]
    reject_precision = len(true_rej) / len(rejected) if rejected else 1.0

    champs = {g["champion"] for g in manifest["groups"] if g["champion"]}
    burst_labeled = {r: l for r, l in labels.items() if l.get("burst_best") is not None}
    burst_hits = sum(1 for r, l in burst_labeled.items()
                     if (r in champs) == bool(l["burst_best"]))
    burst_agreement = burst_hits / len(burst_labeled) if burst_labeled else 1.0

    bucketed = {r: p for r, p in photos.items()
                if p.get("bucket") and labels[r].get("bucket")}
    bucket_hits = sum(1 for r, p in bucketed.items()
                      if p["bucket"] == labels[r]["bucket"])
    bucket_accuracy = bucket_hits / len(bucketed) if bucketed else 1.0

    review_rate = sum(1 for p in photos.values()
                      if p["verdict"] == "needs-review") / len(photos)

    results = {"reject_precision": reject_precision, "burst_agreement": burst_agreement,
               "bucket_accuracy": bucket_accuracy, "review_rate": review_rate}
    ok = (reject_precision >= BARS["reject_precision"]
          and burst_agreement >= BARS["burst_agreement"]
          and bucket_accuracy >= BARS["bucket_accuracy"]
          and review_rate <= BARS["review_rate_max"])
    for k, v in results.items():
        print(f"{k}: {v:.3f}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
