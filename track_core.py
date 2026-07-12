#!/usr/bin/env python3
"""
================================================================================
LFR TRACK ANALYZER  —  PC SIDE
================================================================================
Give it a photo of your track -> outputs speed profile for Arduino.
Optionally sends that profile straight to the Arduino over USB serial.

INSTALL (run once):
    pip install opencv-python numpy pyserial scikit-image

RUN (analyze only):
    python track_analyzer.py photo_of_track.jpg

RUN (analyze + send to Arduino over USB):
    python track_analyzer.py photo_of_track.jpg --send --port COM5
    python track_analyzer.py photo_of_track.jpg --send --port /dev/ttyUSB0

    (use --list-ports to see what's available)

OUTPUT FILES:
    track_profile.h       <- copy into your Arduino project folder
    photo_analyzed.jpg    <- visual showing what was detected (green/yellow/red)

HOW IT WORKS:
    1. Loads track photo
    2. Detects black line using auto-threshold + morphology cleanup
    3. Thins the line to a 1-pixel skeleton (centerline)
    4. Walks the skeleton to get an ordered (x,y) path
    5. Calculates curvature (angle change over a small window) at every point
    6. Labels each point STRAIGHT / CURVE / SHARP
    7. Merges short/noisy segments into clean bigger ones
    8. Writes a C array (track_profile.h) for Arduino
    9. (optional) streams the same data to the Arduino live over USB serial
================================================================================
"""

import cv2
import numpy as np
import sys
import os
import argparse

# ── SETTINGS — change these if detection is wrong on your photo ───────────────

LINE_COLOR      = "black"   # "black" = dark line on light surface
                             # "white" = white line on dark surface
BLUR_KERNEL     = 7         # Gaussian blur before threshold (must be odd)
MORPH_KERNEL    = 5         # morphological kernel size — fills gaps in line

CURVE_STEP      = 15        # points apart used to measure direction change
                             # (raw neighbor-to-neighbor angles are too noisy)
STRAIGHT_DEG    = 8.0       # angle change below this = STRAIGHT
SHARP_DEG       = 30.0      # angle change above this = SHARP (between = CURVE)

SPEED_STRAIGHT  = 210       # must match baseSpeed1 in your Arduino code
SPEED_CURVE     = 155       # must match baseSpeed2
SPEED_SHARP     = 105       # must match baseSpeed3

MIN_SEGMENT_PCT = 3.0       # ignore/merge segments shorter than this % of total path
SMOOTH_WINDOW   = 20        # moving-average window for path smoothing

SERIAL_BAUD     = 115200    # must match Serial.begin() on the Arduino

# ─────────────────────────────────────────────────────────────────────────────

LABELS = ["STRAIGHT", "CURVE", "SHARP"]
SPEEDS = [SPEED_STRAIGHT, SPEED_CURVE, SPEED_SHARP]
COLORS = [(0, 200, 0), (0, 210, 255), (0, 0, 255)]   # BGR: green, yellow, red


def load_image(path):
    img = cv2.imread(path)
    if img is None:
        print(f"ERROR: Cannot open '{path}'")
        sys.exit(1)
    h, w = img.shape[:2]
    print(f"Loaded: {w}x{h} px")
    return img


def extract_mask(img):
    """Convert photo to binary mask where line pixels = 255."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (BLUR_KERNEL, BLUR_KERNEL), 0)
    if LINE_COLOR == "black":
        _, bin_img = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        _, bin_img = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    k = np.ones((MORPH_KERNEL, MORPH_KERNEL), np.uint8)
    cleaned = cv2.morphologyEx(bin_img, cv2.MORPH_CLOSE, k)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, k)
    print(f"Line pixels: {cv2.countNonZero(cleaned)}")
    return cleaned


def skeletonize(mask):
    """
    Thin the line mask to a 1-pixel-wide centerline.

    Uses skimage's Zhang-Suen thinning, which preserves connectivity of the
    input blob. A manual erode/dilate loop was tried first but reliably
    fragments curved lines into dozens of disconnected pieces, breaking the
    path tracer — confirmed with cv2.connectedComponents on a test image
    (20 separate fragments from a single continuous line). Thinning avoids
    that failure mode entirely.
    """
    from skimage.morphology import skeletonize as sk_skeletonize
    skel_bool = sk_skeletonize(mask > 0)
    skel = (skel_bool.astype(np.uint8)) * 255
    print(f"Skeleton: {cv2.countNonZero(skel)} pixels")
    n_components, _ = cv2.connectedComponents(skel, connectivity=8)
    if n_components - 1 > 1:
        print(f"WARNING: skeleton has {n_components - 1} disconnected pieces — "
              "the traced path will only follow the largest reachable piece. "
              "This usually means the line has a gap/break in the photo, or "
              "there's stray dark clutter near the track.")
    return skel


def trace_path(skeleton):
    """
    Walk the skeleton from one end of the track to the other.

    Real skeletons (even after cleanup) are rarely a perfect 1-pixel chain —
    they usually have small spurs and branch points, especially on curves.
    A naive greedy walk dead-ends at the first branch it meets. Instead we
    find the two most-distant pixels on the skeleton (graph diameter, via
    double BFS) and take the shortest path between them — this reliably
    follows the main line and ignores short spurs.
    """
    from collections import deque

    ys, xs = np.where(skeleton > 0)
    if len(xs) == 0:
        print("ERROR: No line detected. Check LINE_COLOR setting.")
        sys.exit(1)
    pix = set(zip(xs.tolist(), ys.tolist()))

    def nbrs(p):
        x, y = p
        return [(x + dx, y + dy) for dx in [-1, 0, 1] for dy in [-1, 0, 1]
                if (dx, dy) != (0, 0) and (x + dx, y + dy) in pix]

    def bfs_farthest(start):
        parent = {start: None}
        q = deque([start])
        last = start
        while q:
            cur = q.popleft()
            last = cur
            for nb in nbrs(cur):
                if nb not in parent:
                    parent[nb] = cur
                    q.append(nb)
        return last, parent

    start_guess = next(iter(pix))
    end_a, _ = bfs_farthest(start_guess)
    end_b, parents = bfs_farthest(end_a)

    path = []
    cur = end_b
    while cur is not None:
        path.append(cur)
        cur = parents[cur]
    path.reverse()

    print(f"Path: {len(path)} points (skeleton had {len(pix)} pixels total)")
    if len(path) < 2 * CURVE_STEP + 5:
        print("WARNING: traced path is very short — detection may have failed "
              "(check LINE_COLOR / lighting / photo crop).")
    if len(path) < 0.5 * len(pix):
        print("NOTE: traced path uses well under half the skeleton pixels — "
              "the track photo may contain a loop, a break, or extra noise "
              "outside the track. Check photo_analyzed.jpg after running.")
    return path


def smooth_path(path):
    xs = np.array([p[0] for p in path], dtype=float)
    ys = np.array([p[1] for p in path], dtype=float)
    k = np.ones(SMOOTH_WINDOW) / SMOOTH_WINDOW

    def s(a):
        return np.convolve(np.pad(a, SMOOTH_WINDOW // 2, 'edge'), k, 'valid')[:len(a)]

    return list(zip(s(xs).tolist(), s(ys).tolist()))


def compute_curvature(path):
    """
    Angle change (degrees) at each point, measured between the direction
    vector CURVE_STEP points behind and CURVE_STEP points ahead. Using a
    window instead of immediate neighbors avoids pixel-level noise.
    Endpoints (where a full window isn't available) inherit the nearest
    valid value.
    """
    n = len(path)
    curv = [0.0] * n
    for i in range(CURVE_STEP, n - CURVE_STEP):
        x0, y0 = path[i - CURVE_STEP]
        x1, y1 = path[i]
        x2, y2 = path[i + CURVE_STEP]
        v1 = np.array([x1 - x0, y1 - y0], dtype=float)
        v2 = np.array([x2 - x1, y2 - y1], dtype=float)
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if n1 < 1e-6 or n2 < 1e-6:
            continue
        cos_a = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
        curv[i] = float(np.degrees(np.arccos(cos_a)))

    # fill the un-computed head/tail with the nearest computed value
    if n > 2 * CURVE_STEP:
        for i in range(CURVE_STEP):
            curv[i] = curv[CURVE_STEP]
        for i in range(n - CURVE_STEP, n):
            curv[i] = curv[n - CURVE_STEP - 1]
    return curv


def classify_points(curv):
    labels = []
    for a in curv:
        if a < STRAIGHT_DEG:
            labels.append(0)   # STRAIGHT
        elif a < SHARP_DEG:
            labels.append(1)   # CURVE
        else:
            labels.append(2)   # SHARP
    return labels


def path_length(path):
    total = 0.0
    for i in range(1, len(path)):
        total += np.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1])
    return total


def build_segments(path, labels):
    """Collapse per-point labels into runs: [(label, start_idx, end_idx), ...]"""
    segments = []
    start = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            segments.append([labels[start], start, i - 1])
            start = i
    return segments


def segment_length(path, seg):
    _, s, e = seg
    total = 0.0
    for i in range(s + 1, e + 1):
        total += np.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1])
    return total


def merge_short_segments(path, segments, total_len):
    """
    Repeatedly fold any segment below MIN_SEGMENT_PCT into whichever
    neighbor is longer, then re-merge any now-adjacent same-label runs.
    """
    changed = True
    while changed and len(segments) > 1:
        changed = False
        for i, seg in enumerate(segments):
            pct = 100.0 * segment_length(path, seg) / total_len
            if pct < MIN_SEGMENT_PCT:
                left_len = segment_length(path, segments[i - 1]) if i > 0 else -1
                right_len = segment_length(path, segments[i + 1]) if i < len(segments) - 1 else -1
                if left_len < 0 and right_len < 0:
                    break  # only one segment total, nothing to merge into
                target = i - 1 if left_len >= right_len else i + 1
                lo, hi = sorted([i, target])
                new_label = segments[lo][0] if lo == target else segments[hi][0]
                # merged segment takes the label of the bigger neighbor
                new_label = segments[target][0]
                merged = [new_label, segments[lo][1], segments[hi][2]]
                segments = segments[:lo] + [merged] + segments[hi + 1:]
                changed = True
                break

    # collapse any now-adjacent equal-label runs
    out = [segments[0]]
    for seg in segments[1:]:
        if seg[0] == out[-1][0]:
            out[-1][2] = seg[2]
        else:
            out.append(seg)
    return out


def analyze(path_img):
    img = load_image(path_img)
    mask = extract_mask(img)
    skel = skeletonize(mask)
    raw_path = trace_path(skel)
    path = smooth_path(raw_path)
    curv = compute_curvature(path)
    labels = classify_points(curv)
    total_len = path_length(path)
    segments = build_segments(path, labels)
    segments = merge_short_segments(path, segments, total_len)

    profile = []
    for label, s, e in segments:
        pct = 100.0 * segment_length(path, [label, s, e]) / total_len
        profile.append({
            "label": LABELS[label],
            "type": label,
            "speed": SPEEDS[label],
            "pct": round(pct, 2),
            "start_idx": s,
            "end_idx": e,
        })

    print("\nSegments detected:")
    for p in profile:
        print(f"  {p['label']:<9} {p['pct']:5.1f}%   speed={p['speed']}")

    return img, path, labels, profile


def draw_visualization(img, path, labels, out_path="photo_analyzed.jpg"):
    vis = img.copy()
    for i in range(1, len(path)):
        pt1 = (int(path[i - 1][0]), int(path[i - 1][1]))
        pt2 = (int(path[i][0]), int(path[i][1]))
        color = COLORS[labels[i]]
        cv2.line(vis, pt1, pt2, color, 3)
    cv2.imwrite(out_path, vis)
    print(f"Wrote {out_path}")


def write_header(profile, out_path="track_profile.h"):
    lines = []
    lines.append("// AUTO-GENERATED by track_analyzer.py — do not hand-edit")
    lines.append("#ifndef TRACK_PROFILE_H")
    lines.append("#define TRACK_PROFILE_H")
    lines.append("")
    lines.append("// type: 0=STRAIGHT 1=CURVE 2=SHARP")
    lines.append("struct TrackSegment {")
    lines.append("  uint8_t type;")
    lines.append("  int16_t speed;")
    lines.append("  float   length_pct;   // % of total track length")
    lines.append("};")
    lines.append("")
    lines.append(f"const TrackSegment TRACK_PROFILE[] = {{")
    for p in profile:
        lines.append(f"  {{{p['type']}, {p['speed']}, {p['pct']:.2f}}},  // {p['label']}")
    lines.append("};")
    lines.append(f"const int TRACK_PROFILE_LEN = {len(profile)};")
    lines.append("")
    lines.append("#endif")
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote {out_path}")


# ── USB serial send ─────────────────────────────────────────────────────────

def list_serial_ports():
    try:
        import serial.tools.list_ports as lp
    except ImportError:
        print("pyserial not installed. Run: pip install pyserial")
        return
    ports = list(lp.comports())
    if not ports:
        print("No serial ports found.")
    for p in ports:
        print(f"  {p.device}   {p.description}")


def send_profile_serial(profile, port, baud=SERIAL_BAUD, timeout=5):
    """
    Protocol (line-based, matches arduino_receive_example.ino):
        PC   -> Arduino : "COUNT,<n>\\n"
        Ard  -> PC      : "OK\\n"
        PC   -> Arduino : "<type>,<speed>,<pct>\\n"   (repeated n times)
        Ard  -> PC      : "OK\\n"   (after each line)
        PC   -> Arduino : "DONE\\n"
        Ard  -> PC      : "READY\\n"
    """
    try:
        import serial
    except ImportError:
        print("ERROR: pyserial not installed. Run: pip install pyserial")
        sys.exit(1)

    print(f"Opening {port} @ {baud} baud ...")
    try:
        ser = serial.Serial(port, baud, timeout=timeout)
    except Exception as e:
        print(f"ERROR: could not open {port}: {e}")
        sys.exit(1)

    import time
    time.sleep(2)  # let the Arduino reset after the port opens

    def send_line(s):
        ser.write((s + "\n").encode("utf-8"))
        resp = ser.readline().decode("utf-8", errors="replace").strip()
        return resp

    resp = send_line(f"COUNT,{len(profile)}")
    if resp != "OK":
        print(f"WARNING: expected OK after COUNT, got: '{resp}'")

    for p in profile:
        resp = send_line(f"{p['type']},{p['speed']},{p['pct']:.2f}")
        if resp != "OK":
            print(f"WARNING: expected OK for segment, got: '{resp}'")

    resp = send_line("DONE")
    print(f"Arduino replied: '{resp}'")
    ser.close()
    print("Profile sent.")
