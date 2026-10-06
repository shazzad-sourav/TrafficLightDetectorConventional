"""
Evaluate main.detect() against hand-labeled lamps.

Ground-truth CSV columns: image,color,x,y,shape,status[,lighting]
  color    RED | GREEN | YELLOW
  shape    circle | arrow | other
  status   gt (scored) | ambig (pedestrian signal, tiny far lamp, unclear color)
  lighting day | night (optional; otherwise --lighting or auto by brightness)

Matching: within each image, a detection matches a lamp of the same color if
its center is within max(20 px, 1.25 x detection radius). Pairs are assigned
greedily by distance, one-to-one, over gt and ambig lamps together.
Detections matched to ambig lamps are excluded from the main numbers.

Usage:
    python evaluate_detector.py --images Input --gt ground_truth.csv --prefix input_
    python evaluate_detector.py --images Input --gt ground_truth.csv --prefix input_ --blur
"""

import argparse
import csv
import math
import os
import sys
from collections import defaultdict

import cv2

from main import detect

COLORS = ("RED", "GREEN", "YELLOW")
NIGHT_BRIGHTNESS = 70  # mean HSV value below this counts as night (auto mode)


def load_gt(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    lamps = defaultdict(list)
    lighting = {}
    for row in rows:
        status = row["status"].strip().lower()
        if status not in ("gt", "ambig"):
            sys.exit(f"Unknown status '{row['status']}' in {path}")
        lamps[row["image"].strip()].append({
            "color": row["color"].strip().upper(),
            "x": float(row["x"]),
            "y": float(row["y"]),
            "shape": row.get("shape", "circle").strip().lower() or "circle",
            "status": status,
        })
        if row.get("lighting"):
            lighting[row["image"].strip()] = row["lighting"].strip().lower()
    return lamps, lighting


def load_lighting(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {r["image"].strip(): r["lighting"].strip().lower() for r in csv.DictReader(f)}


def find_image(folder, name, prefix):
    candidates = [name]
    if prefix and name.startswith(prefix):
        candidates.append(name[len(prefix):])
    elif prefix:
        candidates.append(prefix + name)
    for candidate in candidates:
        path = os.path.join(folder, candidate)
        if os.path.isfile(path):
            return path
    return None


def auto_lighting(img):
    value = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 2].mean()
    return "night" if value < NIGHT_BRIGHTNESS else "day"


def match(detections, lamps):
    """Greedy one-to-one matching by distance. Returns {det_index: lamp_index}."""
    pairs = []
    for di, d in enumerate(detections):
        limit = max(20.0, 1.25 * d["radius"])
        for li, lamp in enumerate(lamps):
            if lamp["color"] != d["label"]:
                continue
            dist = math.hypot(d["x"] - lamp["x"], d["y"] - lamp["y"])
            if dist <= limit:
                pairs.append((dist, di, li))
    pairs.sort()
    used_d, used_l, result = set(), set(), {}
    for _, di, li in pairs:
        if di in used_d or li in used_l:
            continue
        used_d.add(di)
        used_l.add(li)
        result[di] = li
    return result


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def main():
    ap = argparse.ArgumentParser(description="Score main.detect() against labeled lamps.")
    ap.add_argument("--images", required=True, help="Folder containing the images")
    ap.add_argument("--gt", required=True, help="Ground-truth CSV")
    ap.add_argument("--prefix", default="", help="Prefix in GT image names that the files on "
                    "disk may lack (or vice versa), e.g. input_")
    ap.add_argument("--blur", action="store_true", help="Run the detector with the Gaussian blur")
    ap.add_argument("--lighting", help="CSV with columns image,lighting (day/night)")
    ap.add_argument("--details", default="details.csv", help="Per-item output CSV")
    args = ap.parse_args()

    lamps_by_image, lighting = load_gt(args.gt)
    if args.lighting:
        lighting.update(load_lighting(args.lighting))

    tp = fp = fn = ambig_det = ambig_missed = n_det = 0
    by_color = {c: [0, 0, 0] for c in COLORS}
    by_light = defaultdict(lambda: [0, 0, 0])
    by_shape = defaultdict(lambda: [0, 0])  # found, total (gt lamps only)
    details = []
    auto_used = False
    missing = []

    for name in sorted(lamps_by_image, key=lambda s: (len(s), s)):
        path = find_image(args.images, name, args.prefix)
        if path is None:
            missing.append(name)
            continue
        img = cv2.imread(path)
        lamps = lamps_by_image[name]
        _, detections = detect(img, use_blur=args.blur)
        n_det += len(detections)

        light = lighting.get(name)
        if light is None:
            light, auto_used = auto_lighting(img), True

        matched = match(detections, lamps)
        matched_lamps = set(matched.values())

        for di, d in enumerate(detections):
            if di in matched:
                lamp = lamps[matched[di]]
                if lamp["status"] == "gt":
                    outcome = "TP"
                    tp += 1
                    by_color[d["label"]][0] += 1
                    by_light[light][0] += 1
                else:
                    outcome = "ambig_det"
                    ambig_det += 1
            else:
                outcome = "FP"
                fp += 1
                by_color[d["label"]][1] += 1
                by_light[light][1] += 1
            details.append([name, light, outcome, d["label"], d["x"], d["y"], d["radius"], ""])

        for li, lamp in enumerate(lamps):
            if lamp["status"] == "gt":
                by_shape[lamp["shape"]][1] += 1
                if li in matched_lamps:
                    by_shape[lamp["shape"]][0] += 1
                    continue
                fn += 1
                by_color[lamp["color"]][2] += 1
                by_light[light][2] += 1
                details.append([name, light, "FN", lamp["color"], int(lamp["x"]), int(lamp["y"]), "", lamp["shape"]])
            elif li not in matched_lamps:
                ambig_missed += 1

    if missing:
        print(f"Warning: {len(missing)} image(s) not found, e.g. {missing[0]}")
    scored = len(lamps_by_image) - len(missing)
    n_gt = tp + fn

    print(f"Images: {scored}   ground-truth lamps: {n_gt}   detections: {n_det}"
          f"{'   (blur on)' if args.blur else ''}")
    print(f"TP={tp}  FP={fp}  FN={fn}   ambiguous detections={ambig_det}  "
          f"ambiguous lamps not found={ambig_missed}\n")
    for label, (t, f_, n_) in (
        ("Main (ambiguous excluded)", (tp, fp, fn)),
        ("Worst case", (tp, fp + ambig_det, fn + ambig_missed)),
        ("Best case", (tp + ambig_det, fp, fn)),
    ):
        p, r, f1 = prf(t, f_, n_)
        print(f"{label:<27}precision={p:.3f}  recall={r:.3f}  F1={f1:.3f}")

    print("\nBy color:")
    for c in COLORS:
        t, f_, n_ = by_color[c]
        p, r, _ = prf(t, f_, n_)
        print(f"  {c:<7} TP={t:>3} FP={f_:>3} FN={n_:>3}  precision={p:.3f}  recall={r:.3f}")
    print("By lamp shape (recall):")
    for shape in sorted(by_shape):
        found, total = by_shape[shape]
        print(f"  {shape:<7} {found}/{total} = {found / total:.3f}")
    print("By lighting" + (" (auto-detected for some images)" if auto_used else "") + ":")
    for light in sorted(by_light):
        t, f_, n_ = by_light[light]
        p, r, _ = prf(t, f_, n_)
        print(f"  {light:<5} TP={t:>3} FP={f_:>3} FN={n_:>3}  precision={p:.3f}  recall={r:.3f}")

    with open(args.details, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image", "lighting", "outcome", "color", "x", "y", "radius", "shape"])
        w.writerows(details)
    print(f"\nPer-detection details saved to {args.details}")


if __name__ == "__main__":
    main()
