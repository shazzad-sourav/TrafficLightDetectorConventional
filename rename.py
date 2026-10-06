"""
Batch-rename the images in a folder to a numbered sequence, e.g.
input_traffic_light_1.jpg, input_traffic_light_2.jpg, ...

Safe by default: it only PREVIEWS the new names. Add --apply to rename.

Usage:
    python rename_images.py "C:\\path\\to\\images"                 # preview
    python rename_images.py "C:\\path\\to\\images" --apply         # rename in place
    python rename_images.py "C:\\path\\to\\images" --prefix img_ --start 101 --apply
    python rename_images.py "C:\\path\\to\\images" --copy-to renamed --apply   # keep originals
"""

import argparse
import os
import re
import shutil
import sys
import uuid

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp")


def natural_key(name):
    """Sort 'img2' before 'img10' (numbers compared as numbers)."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def build_plan(folder, prefix, start, digits):
    files = sorted(
        (f for f in os.listdir(folder)
         if os.path.isfile(os.path.join(folder, f)) and f.lower().endswith(IMAGE_EXTENSIONS)),
        key=natural_key,
    )
    plan = []
    for offset, old in enumerate(files):
        ext = os.path.splitext(old)[1].lower()
        number = str(start + offset).zfill(digits)
        plan.append((old, f"{prefix}{number}{ext}"))
    return plan


def apply_in_place(folder, plan):
    """Two-phase rename so names that overlap (e.g. 2.jpg -> 1.jpg, 1.jpg -> 2.jpg) never clash."""
    token = uuid.uuid4().hex[:8]
    staged = []
    for old, new in plan:
        if old == new:
            continue
        temp = f".tmp_{token}_{old}"
        os.rename(os.path.join(folder, old), os.path.join(folder, temp))
        staged.append((temp, new))
    for temp, new in staged:
        os.rename(os.path.join(folder, temp), os.path.join(folder, new))


def apply_copy(folder, out_folder, plan):
    os.makedirs(out_folder, exist_ok=True)
    for old, new in plan:
        shutil.copy2(os.path.join(folder, old), os.path.join(out_folder, new))


def main():
    p = argparse.ArgumentParser(description="Batch-rename images to a numbered sequence.")
    p.add_argument("folder", help="Folder containing the images")
    p.add_argument("--prefix", default="input_traffic_light_", help="New name prefix (default: input_traffic_light_)")
    p.add_argument("--start", type=int, default=1, help="First number (default: 1)")
    p.add_argument("--digits", type=int, default=0, help="Zero-pad width, e.g. 3 gives 001 (default: no padding)")
    p.add_argument("--copy-to", help="Copy renamed files into this folder instead of renaming in place")
    p.add_argument("--apply", action="store_true", help="Actually rename (without this, only a preview is shown)")
    args = p.parse_args()

    if not os.path.isdir(args.folder):
        sys.exit(f"Folder not found: {args.folder}")

    plan = build_plan(args.folder, args.prefix, args.start, args.digits)
    if not plan:
        sys.exit("No images found.")

    width = max(len(old) for old, _ in plan)
    for old, new in plan:
        print(f"{old.ljust(width)}  ->  {new}")
    print(f"\n{len(plan)} image(s).")

    if not args.apply:
        print("Preview only. Re-run with --apply to rename.")
        return

    if args.copy_to:
        out = args.copy_to if os.path.isabs(args.copy_to) else os.path.join(args.folder, args.copy_to)
        apply_copy(args.folder, out, plan)
        print(f"Copied to: {out}")
    else:
        apply_in_place(args.folder, plan)
        print("Renamed in place.")


if __name__ == "__main__":
    main()