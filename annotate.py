#!/usr/bin/env python3
"""
Interactive annotation tool for crop + mask definition.

Usage (run from repo root):
    python manual_mask_extraction/annotate.py [--videos-dir DIR] [--videos A.mp4 ...]

Phase 1 — Crop region
    Left-drag       Draw crop rectangle
    ← / →           Step ±1 frame
    , / .           Step ±30 frames
    < / >           Jump ±10 % of total duration
    Enter / Space   Confirm crop
    R               Reset current crop
    S               Skip this video
    Q               Save and quit

Phase 2 — Mask shapes  (RECT mode by default)
    Left-drag       Draw a rectangular mask           [RECT mode]
    Enter           Add the pending rectangle         [RECT mode]
    P               Switch to polygon mode
    Left-click      Add a polygon vertex              [POLY mode]
    Enter           Confirm polygon (need ≥ 3 pts)    [POLY mode]
    Z               Undo last vertex                  [POLY mode]
    R               Cancel poly / reset rect
    U               Undo last confirmed mask (either type)
    N               Finish masks, move to next video
    Q               Save config and quit

Config saved to manual_mask_extraction/config.json.
Re-running loads existing annotations for editing.
"""

import json
import os
import sys
from glob import glob
from pathlib import Path

import cv2
import numpy as np

MAX_DISPLAY_W = 1280
MAX_DISPLAY_H = 720

VIDEOS_DIR  = Path(__file__).parent.parent / "mask_extraction_samples"
CONFIG_PATH = Path(__file__).parent / "config.json"

RECT_COLOR   = (220, 80,  0)    # confirmed rect  (BGR)
POLY_COLOR   = (0,  80, 220)    # confirmed poly
ACTIVE_COLOR = (0, 220, 220)    # shape being drawn
CROP_COLOR   = (0,   0, 220)    # crop rect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def display_scale(w, h):
    scale = 1.0
    if w > MAX_DISPLAY_W:
        scale = min(scale, MAX_DISPLAY_W / w)
    if h > MAX_DISPLAY_H:
        scale = min(scale, MAX_DISPLAY_H / h)
    return scale


def put_lines(img, lines, x=10, y_start=25, dy=22,
              font_scale=0.52, color=(255, 255, 255)):
    font = cv2.FONT_HERSHEY_SIMPLEX
    for i, line in enumerate(lines):
        y = y_start + i * dy
        cv2.putText(img, line, (x, y), font, font_scale, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, line, (x, y), font, font_scale, color, 1, cv2.LINE_AA)


def fmt_time(frames, fps):
    secs = int(frames / fps) if fps > 0 else 0
    return f"{secs // 60}:{secs % 60:02d}"


def draw_mask_on(img, mask, scale):
    """Draw one mask (rect list or poly dict) onto img in display coordinates."""
    if isinstance(mask, dict) and mask.get("type") == "poly":
        pts = np.array(
            [(int(p[0] * scale), int(p[1] * scale)) for p in mask["points"]],
            dtype=np.int32,
        )
        overlay = img.copy()
        cv2.fillPoly(overlay, [pts], POLY_COLOR)
        cv2.addWeighted(overlay, 0.35, img, 0.65, 0, img)
        cv2.polylines(img, [pts], True, POLY_COLOR, 2)
    else:
        x1, y1, x2, y2 = [int(v * scale) for v in mask]
        overlay = img.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), RECT_COLOR, -1)
        cv2.addWeighted(overlay, 0.35, img, 0.65, 0, img)
        cv2.rectangle(img, (x1, y1), (x2, y2), RECT_COLOR, 2)


# ---------------------------------------------------------------------------
# Phase 1: crop with frame scrubbing
# ---------------------------------------------------------------------------

def phase1_crop(window, video_path, existing_crop=None):
    """
    Let the user scrub through the video, then draw a crop rectangle.
    Returns (crop_rect_pixels, selected_frame_bgr) or ("QUIT", None) or (None, None).
    """
    cap = cv2.VideoCapture(str(video_path))
    total   = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps     = cap.get(cv2.CAP_PROP_FPS) or 25.0
    orig_w  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale   = display_scale(orig_w, orig_h)
    dw, dh  = int(orig_w * scale), int(orig_h * scale)

    cur_idx   = 0
    cur_frame = None

    def seek(n):
        nonlocal cur_frame, cur_idx
        cur_idx = max(0, min(int(n), total - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, cur_idx)
        ret, f = cap.read()
        if ret:
            cur_frame = f

    seek(0)

    # Rect drawing state
    drawing   = False
    drag_start = None
    pending   = None                                        # (x1,y1,x2,y2) display
    confirmed = None                                        # (x1,y1,x2,y2) display
    mouse_pos = [0, 0]

    if existing_crop:
        confirmed = tuple(int(v * scale) for v in existing_crop)

    def on_mouse(event, x, y, flags, param):
        nonlocal drawing, drag_start, pending
        mouse_pos[0], mouse_pos[1] = x, y
        if event == cv2.EVENT_LBUTTONDOWN:
            drawing    = True
            drag_start = (x, y)
            pending    = None
        elif event == cv2.EVENT_MOUSEMOVE and drawing:
            pass   # redrawn each frame
        elif event == cv2.EVENT_LBUTTONUP and drawing:
            drawing = False
            if drag_start:
                x1, y1 = drag_start
                x2, y2 = x, y
                if abs(x2 - x1) > 4 and abs(y2 - y1) > 4:
                    pending = (min(x1,x2), min(y1,y2),
                               max(x1,x2), max(y1,y2))
            drag_start = None

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, dw, dh)
    cv2.setMouseCallback(window, on_mouse)

    jump_pct = max(1, total // 10)     # 10 % jump
    jump_med = max(1, total // 50)     # 2 % / ~30 frames

    while True:
        if cur_frame is None:
            break
        base = cv2.resize(cur_frame, (dw, dh))
        show = base.copy()

        # Confirmed crop
        if confirmed:
            cv2.rectangle(show, confirmed[:2], confirmed[2:], CROP_COLOR, 2)

        # Live drag
        if drawing and drag_start:
            x1, y1 = drag_start
            x2, y2 = mouse_pos
            cv2.rectangle(show, (min(x1,x2), min(y1,y2)),
                          (max(x1,x2), max(y1,y2)), (180, 180, 180), 1)

        # Pending (not yet confirmed)
        if pending:
            cv2.rectangle(show, pending[:2], pending[2:], (0, 140, 255), 2)

        # Progress bar at bottom
        bar_y = dh - 6
        bar_w = int(dw * cur_idx / max(1, total - 1))
        cv2.rectangle(show, (0, bar_y), (dw, dh), (40, 40, 40), -1)
        cv2.rectangle(show, (0, bar_y), (bar_w, dh), (0, 200, 255), -1)

        put_lines(show, [
            "PHASE 1: Draw CROP region",
            "\u2190\u2192:±1 frame   , . :±30   < > :±10%   Enter:confirm   R:reset   S:skip   Q:quit",
            f"Frame {cur_idx}/{total-1}  ({fmt_time(cur_idx, fps)} / {fmt_time(total, fps)})"
            + ("   [crop confirmed]" if confirmed else "   [no crop yet]"),
        ], color=(200, 220, 255))

        cv2.imshow(window, show)
        raw_key = cv2.waitKey(20)
        key = raw_key & 0xFF

        if key in (13, 32):       # Enter / Space — confirm
            if pending:
                confirmed = pending
                pending = None
            if confirmed:
                result = tuple(int(v / scale) for v in confirmed)
                frame_copy = cur_frame.copy()
                cap.release()
                return result, frame_copy
        elif key == ord('r'):
            confirmed = None
            pending   = None
        elif key == ord('s'):
            cap.release()
            return None, None
        elif key == ord('q'):
            cap.release()
            return "QUIT", None
        # Frame navigation
        elif key in (81, 2) or raw_key == 2424832:   # left arrow (Linux / Windows)
            seek(cur_idx - 1)
        elif key in (83, 3) or raw_key == 2555904:  # right arrow (Linux / Windows)
            seek(cur_idx + 1)
        elif key == ord(','):
            seek(cur_idx - jump_med)
        elif key == ord('.'):
            seek(cur_idx + jump_med)
        elif key == ord('<'):
            seek(cur_idx - jump_pct)
        elif key == ord('>'):
            seek(cur_idx + jump_pct)

    cap.release()
    return None, None


# ---------------------------------------------------------------------------
# Phase 2: mask shapes (rect + polygon)
# ---------------------------------------------------------------------------

def phase2_masks(window, crop_frame, existing_masks=None):
    """
    Draw rectangular or polygon masks on the cropped frame.
    Returns list of masks (each is [x1,y1,x2,y2] or {"type":"poly","points":[...]})
    or "QUIT".
    Coordinates are in crop-relative pixels.
    """
    h, w   = crop_frame.shape[:2]
    scale  = display_scale(w, h)
    dw, dh = int(w * scale), int(h * scale)
    base   = cv2.resize(crop_frame, (dw, dh))

    masks = [m for m in (existing_masks or [])]
    mode  = "rect"    # "rect" | "poly"

    # Rect state
    rect_drawing   = False
    rect_start     = None
    rect_pending   = None
    # Poly state
    poly_pts = []     # (x, y) in display coords
    mouse_pos = [0, 0]

    def on_mouse(event, x, y, flags, param):
        nonlocal rect_drawing, rect_start, rect_pending
        mouse_pos[0], mouse_pos[1] = x, y
        if mode == "rect":
            if event == cv2.EVENT_LBUTTONDOWN:
                rect_drawing = True
                rect_start   = (x, y)
                rect_pending = None
            elif event == cv2.EVENT_MOUSEMOVE and rect_drawing:
                pass
            elif event == cv2.EVENT_LBUTTONUP and rect_drawing:
                rect_drawing = False
                if rect_start:
                    x1, y1 = rect_start
                    if abs(x - x1) > 4 and abs(y - y1) > 4:
                        rect_pending = (min(x1,x), min(y1,y),
                                        max(x1,x), max(y1,y))
                rect_start = None
        elif mode == "poly":
            if event == cv2.EVENT_LBUTTONDOWN:
                poly_pts.append((x, y))

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, dw, max(dh, 120))
    cv2.setMouseCallback(window, on_mouse)

    while True:
        show = base.copy()

        # Confirmed masks
        for m in masks:
            draw_mask_on(show, m, scale)

        # Active rect
        if mode == "rect":
            if rect_drawing and rect_start:
                x1, y1 = rect_start
                x2, y2 = mouse_pos
                cv2.rectangle(show, (min(x1,x2), min(y1,y2)),
                              (max(x1,x2), max(y1,y2)), (150, 150, 150), 1)
            if rect_pending:
                cv2.rectangle(show, rect_pending[:2], rect_pending[2:],
                              ACTIVE_COLOR, 2)

        # Active polygon
        if mode == "poly":
            for pt in poly_pts:
                cv2.circle(show, pt, 5, ACTIVE_COLOR, -1)
                cv2.circle(show, pt, 5, (0, 0, 0), 1)
            if len(poly_pts) >= 2:
                for i in range(len(poly_pts) - 1):
                    cv2.line(show, poly_pts[i], poly_pts[i+1], ACTIVE_COLOR, 1)
            if poly_pts:
                # rubber band: last pt → mouse
                cv2.line(show, poly_pts[-1],
                         (mouse_pos[0], mouse_pos[1]), ACTIVE_COLOR, 1)
            if len(poly_pts) >= 3:
                # closing preview: mouse → first pt
                cv2.line(show, (mouse_pos[0], mouse_pos[1]),
                         poly_pts[0], (0, 150, 150), 1)

        # Instructions
        if mode == "rect":
            hint1 = f"RECT mode — {len(masks)} mask(s)"
            hint2 = "Drag:draw | Enter:add | U:undo | P:polygon | N:done | Q:quit"
        else:
            hint1 = f"POLY mode — {len(masks)} mask(s), {len(poly_pts)} pts so far"
            hint2 = "Click:vertex | Enter:confirm(≥3 pts) | Z:undo-pt | R:back-to-rect | U:undo | N:done | Q:quit"

        put_lines(show, [hint1, hint2], color=(200, 255, 200))
        cv2.imshow(window, show)
        key = cv2.waitKey(20) & 0xFF

        if key in (13, 32):       # Enter / Space
            if mode == "rect" and rect_pending:
                orig = tuple(int(v / scale) for v in rect_pending)
                masks.append(list(orig))
                print(f"  + rect mask {len(masks)}: {orig}")
                rect_pending = None
            elif mode == "poly" and len(poly_pts) >= 3:
                orig_pts = [[int(x / scale), int(y / scale)] for x, y in poly_pts]
                masks.append({"type": "poly", "points": orig_pts})
                print(f"  + poly mask {len(masks)}: {len(orig_pts)} vertices")
                poly_pts.clear()

        elif key == ord('p'):
            mode = "poly"
            rect_pending = None

        elif key == ord('r'):
            if mode == "poly":
                poly_pts.clear()
                mode = "rect"
            else:
                rect_pending = None

        elif key == ord('z'):     # undo last poly vertex
            if mode == "poly" and poly_pts:
                poly_pts.pop()

        elif key == ord('u'):     # undo last confirmed mask
            if masks:
                removed = masks.pop()
                print(f"  - removed mask: {removed}")

        elif key == ord('n'):
            return masks

        elif key == ord('q'):
            return "QUIT"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="Manual mask annotation tool")
    p.add_argument("--videos-dir", type=Path, default=VIDEOS_DIR,
                   help="Root directory to scan for .mp4 files")
    p.add_argument("--videos", type=Path, nargs="+", default=None,
                   help="Explicit list of video files (overrides --videos-dir)")
    p.add_argument("--config", type=Path, default=CONFIG_PATH,
                   help="Config JSON path")
    return p.parse_args()


def _save(config, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"  [saved] {path}")


def main():
    args = parse_args()
    videos_dir  = args.videos_dir
    config_path = args.config

    if args.videos:
        video_paths = [str(v) for v in args.videos]
        videos_dir  = Path(os.path.commonpath([str(v) for v in args.videos]))
        if videos_dir.is_file():
            videos_dir = videos_dir.parent
    else:
        video_paths = sorted(glob(str(videos_dir / "**" / "*.mp4"), recursive=True))

    if not video_paths:
        print("No .mp4 files found")
        sys.exit(1)

    print(f"Found {len(video_paths)} video(s)  [base: {videos_dir}]\n")

    config = {}
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
        print(f"Loaded existing config ({len(config)} entries)")

    window = "Manual Mask Annotator"

    for idx, video_path in enumerate(video_paths):
        try:
            rel = str(Path(video_path).relative_to(videos_dir))
        except ValueError:
            rel = Path(video_path).name
        existing = config.get(rel, {})

        print(f"\n{'='*60}")
        print(f"[{idx+1}/{len(video_paths)}] {rel}")

        # Phase 1: crop (with frame scrubbing)
        crop_result, selected_frame = phase1_crop(
            window, video_path,
            existing_crop=existing.get("crop"),
        )

        if crop_result == "QUIT":
            print("Quit requested — saving config.")
            break
        if crop_result is None:
            print("  Skipped.")
            continue

        crop = list(crop_result)
        cx1, cy1, cx2, cy2 = crop
        crop_frame = selected_frame[cy1:cy2, cx1:cx2]
        if crop_frame.size == 0:
            print("  ERROR: empty crop, skipping.")
            continue
        print(f"  Crop: {crop}")

        # Phase 2: masks
        masks_result = phase2_masks(
            window, crop_frame,
            existing_masks=existing.get("masks", []),
        )

        if masks_result == "QUIT":
            config[rel] = {"crop": crop, "masks": existing.get("masks", [])}
            _save(config, config_path)
            print("Quit requested — saving config.")
            break

        config[rel] = {"crop": crop, "masks": masks_result}
        print(f"  Masks: {len(masks_result)}")
        _save(config, config_path)

    cv2.destroyAllWindows()
    _save(config, config_path)
    print(f"\nAnnotation done. Config: {config_path}")


if __name__ == "__main__":
    main()
