"""
Traffic light detection with classical computer vision.

HSV color masks + Hough circle detection for red, green and yellow lamps.

Usage:
    python main.py                                   # folder dialogs
    python main.py --input Input --output Output     # no dialogs
    python main.py --input Input --output Output --blur --no-display

From code:
    from main import detect
    annotated, detections = detect(cv2.imread("Input/traffic_light_54.jpg"))
"""

import argparse
import os
import sys

import cv2
import numpy as np

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp")

# HSV thresholds (OpenCV hue range is 0-180)
LOWER_RED1, UPPER_RED1 = np.array([0, 100, 100]), np.array([10, 255, 255])
LOWER_RED2, UPPER_RED2 = np.array([160, 100, 100]), np.array([180, 255, 255])
LOWER_GREEN, UPPER_GREEN = np.array([40, 50, 50]), np.array([90, 255, 255])
LOWER_YELLOW, UPPER_YELLOW = np.array([15, 150, 150]), np.array([35, 255, 255])

TOP_FRACTION = 0.4   # only keep candidates in the top 40% of the image
WINDOW = 5           # half-size of the mask check window around a center

# label: (Hough minDist, Hough param2, minimum mean mask value in the window)
COLOR_SETTINGS = {
    "RED": (80, 10, 50),
    "GREEN": (60, 10, 100),
    "YELLOW": (30, 5, 50),
}


def color_masks(hsv):
    red = cv2.add(cv2.inRange(hsv, LOWER_RED1, UPPER_RED1),
                  cv2.inRange(hsv, LOWER_RED2, UPPER_RED2))
    green = cv2.inRange(hsv, LOWER_GREEN, UPPER_GREEN)
    yellow = cv2.inRange(hsv, LOWER_YELLOW, UPPER_YELLOW)
    return {"RED": red, "GREEN": green, "YELLOW": yellow}


def _window_mean(mask, x, y):
    """Mean mask value in a (2*WINDOW)x(2*WINDOW) window centered on (x, y)."""
    height, width = mask.shape
    total, count = 0.0, 0
    for m in range(-WINDOW, WINDOW):
        for n in range(-WINDOW, WINDOW):
            yy, xx = y + m, x + n
            if yy >= height or xx >= width:
                continue
            total += mask[yy, xx]
            count += 1
    return total / count if count else 0.0


def detect(img, use_blur=False):
    """
    Detect lit traffic lamps in a BGR image.

    Returns (annotated_copy, detections) where detections is a list of
    {'label': 'RED'|'GREEN'|'YELLOW', 'x': int, 'y': int, 'radius': int}.
    The input image is not modified.
    """
    source = cv2.GaussianBlur(img, (9, 9), 3) if use_blur else img
    hsv = cv2.cvtColor(source, cv2.COLOR_BGR2HSV)
    masks = color_masks(hsv)

    annotated = img.copy()
    height, width = img.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    detections = []

    for label, (min_dist, param2, min_fill) in COLOR_SETTINGS.items():
        mask = masks[label]
        circles = cv2.HoughCircles(mask, cv2.HOUGH_GRADIENT, 1, min_dist,
                                   param1=50, param2=param2,
                                   minRadius=0, maxRadius=30)
        if circles is None:
            continue

        for cx, cy, cr in np.uint16(np.around(circles))[0, :]:
            # Plain Python ints: uint16 arithmetic with negative offsets
            # raises OverflowError on NumPy 2.
            x, y, radius = int(cx), int(cy), int(cr)
            if x > width or y > height or y > height * TOP_FRACTION:
                continue
            if _window_mean(mask, x, y) <= min_fill:
                continue

            cv2.circle(annotated, (x, y), radius + 10, (0, 255, 0), 2)
            cv2.putText(annotated, label, (x, y), font, 1, (255, 0, 0), 2, cv2.LINE_AA)
            # Kept from the original algorithm: an accepted lamp is outlined on
            # the mask, which can affect later candidates of the same color.
            cv2.circle(mask, (x, y), radius + 30, (255, 255, 255), 2)
            detections.append({"label": label, "x": x, "y": y, "radius": radius})

    return annotated, detections


def list_images(folder):
    return sorted(f for f in os.listdir(folder) if f.lower().endswith(IMAGE_EXTENSIONS))


def process_folder(input_dir, output_dir, use_blur=False, display=True):
    os.makedirs(output_dir, exist_ok=True)
    files = list_images(input_dir)
    if not files:
        print(f"No images found in {input_dir}")
        return

    for name in files:
        image = cv2.imread(os.path.join(input_dir, name))
        if image is None:
            print(f"Skipped (unreadable): {name}")
            continue

        annotated, detections = detect(image, use_blur=use_blur)
        cv2.imwrite(os.path.join(output_dir, name), annotated)
        found = ", ".join(d["label"] for d in detections) or "none"
        print(f"{name}: {found}")

        if display:
            try:
                cv2.imshow("Input Image", image)
                cv2.imshow("Output Image", annotated)
                key = cv2.waitKey(0) & 0xFF
            except cv2.error:
                print("No display available; continuing without preview.")
                display = False
                continue
            if key == ord("q"):
                display = False
                cv2.destroyAllWindows()

    if display:
        cv2.destroyAllWindows()
    print(f"Done: {len(files)} image(s) written to {output_dir}")


def ask_with_dialogs():
    """Tkinter dialogs for input folder, output folder and the blur choice."""
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.withdraw()
    input_dir = filedialog.askdirectory(title="Select Input Directory")
    if not input_dir:
        return None
    output_dir = filedialog.askdirectory(title="Select Output Directory")
    if not output_dir:
        return None
    use_blur = messagebox.askyesno(
        "Gaussian Filter", "If the images are very sharp choose Yes. Otherwise choose No.")
    root.destroy()
    return input_dir, output_dir, use_blur


def main():
    parser = argparse.ArgumentParser(description="Detect traffic lights in a folder of images.")
    parser.add_argument("--input", help="Folder of input images (omit both folders to use dialogs)")
    parser.add_argument("--output", help="Folder for annotated images")
    parser.add_argument("--blur", action="store_true", help="Apply a 9x9 Gaussian blur before detection")
    parser.add_argument("--no-display", action="store_true", help="Do not show preview windows")
    args = parser.parse_args()

    if args.input or args.output:
        if not (args.input and args.output):
            parser.error("--input and --output must be given together")
        if not os.path.isdir(args.input):
            sys.exit(f"Input folder not found: {args.input}")
        input_dir, output_dir, use_blur = args.input, args.output, args.blur
    else:
        choice = ask_with_dialogs()
        if choice is None:
            print("Cancelled.")
            return
        input_dir, output_dir, use_blur = choice
        use_blur = use_blur or args.blur

    process_folder(input_dir, output_dir, use_blur=use_blur, display=not args.no_display)


if __name__ == "__main__":
    main()
