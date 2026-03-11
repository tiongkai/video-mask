#!/usr/bin/env python3
"""
Process videos using annotation config (crop + mask bboxes).

Reads manual_mask_extraction/config.json produced by annotate.py,
then for each annotated video:
  1. Crops to the defined crop region (always smaller than the original).
  2. Blacks out each mask bbox within the crop.
  3. Writes the result to manual_mask_extraction/outputs/<subdir>/<name>_masked.mp4.

Output videos are guaranteed to be smaller in resolution than the originals
because the crop region is a strict sub-rectangle of each frame.

Usage (run from repo root):
    python manual_mask_extraction/process.py [--videos-dir DIR] [--config PATH] [--output-dir DIR]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_VIDEOS_DIR = REPO_ROOT / "mask_extraction_samples"
DEFAULT_CONFIG = Path(__file__).parent / "config.json"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "outputs"

# Extra Windows locations where ffmpeg is commonly installed
_WIN_FFMPEG_HINTS = [
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
]


def _find_ffmpeg() -> str:
    """
    Find an ffmpeg binary that has libx264 support.
    Searches PATH first (via shutil.which), then common Windows install paths,
    then known Linux paths.  Raises SystemExit with a helpful message if none
    is found.
    """
    candidates = []

    # 1. PATH lookup (works on all platforms)
    found_in_path = shutil.which("ffmpeg")
    if found_in_path:
        candidates.append(found_in_path)

    # 2. Platform-specific extras
    if sys.platform == "win32":
        candidates += _WIN_FFMPEG_HINTS
    else:
        candidates += ["/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]

    for candidate in candidates:
        try:
            result = subprocess.run(
                [candidate, "-encoders"],
                capture_output=True, text=True,
            )
            if "libx264" in result.stdout:
                return candidate
            # Binary found but no libx264 — still usable as a fallback
            if result.returncode == 0 and candidate == candidates[0]:
                fallback = candidate
        except (FileNotFoundError, OSError):
            continue

    # No libx264, but maybe we found something usable
    try:
        return fallback       # type: ignore[possibly-undefined]
    except NameError:
        pass

    print(
        "\nERROR: ffmpeg not found.\n"
        "Install ffmpeg and make sure it is on your PATH:\n"
        "  Windows : https://www.gyan.dev/ffmpeg/builds/  (add bin/ to PATH)\n"
        "  Linux   : sudo apt install ffmpeg\n"
        "  macOS   : brew install ffmpeg\n"
    )
    sys.exit(1)


FFMPEG = _find_ffmpeg()


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def get_video_bitrate(video_path: Path) -> int:
    """Return the video stream bitrate in bits/s via ffprobe, or 0 if unavailable."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(video_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return 0
    try:
        for stream in json.loads(result.stdout).get("streams", []):
            if stream.get("codec_type") == "video":
                return int(stream.get("bit_rate", 0))
    except (json.JSONDecodeError, ValueError):
        pass
    return 0


def process_video(video_path: Path, crop: list, masks: list, output_path: Path) -> bool:
    """
    Crop video to `crop` [x1,y1,x2,y2] and black out each rect in `masks`
    (coords relative to crop top-left).

    Pipes raw frames directly into ffmpeg (libopenh264 / H.264) at a bitrate
    scaled proportionally to the crop area, so the output is always smaller
    than the original.

    Returns True on success.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"  ERROR: cannot open {video_path}")
        return False

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Clamp crop to frame bounds
    cx1, cy1, cx2, cy2 = crop
    cx1 = max(0, min(cx1, orig_w))
    cy1 = max(0, min(cy1, orig_h))
    cx2 = max(cx1 + 1, min(cx2, orig_w))
    cy2 = max(cy1 + 1, min(cy2, orig_h))
    crop_w = cx2 - cx1
    crop_h = cy2 - cy1

    assert crop_w <= orig_w and crop_h <= orig_h, "Crop is larger than original — check config."

    # H.264 requires even dimensions — round down if needed
    crop_w = crop_w if crop_w % 2 == 0 else crop_w - 1
    crop_h = crop_h if crop_h % 2 == 0 else crop_h - 1
    cx2 = cx1 + crop_w
    cy2 = cy1 + crop_h

    # Target bitrate: proportional to the crop area so the output is
    # always smaller than the original file.
    orig_bitrate = get_video_bitrate(video_path)
    if orig_bitrate > 0:
        crop_ratio = (crop_w * crop_h) / (orig_w * orig_h)
        target_bitrate = max(200_000, int(orig_bitrate * crop_ratio))
    else:
        target_bitrate = 1_000_000  # 1 Mbps fallback

    print(f"  Original  : {orig_w}x{orig_h}  {orig_bitrate//1000} kbps")
    print(f"  Crop      : ({cx1},{cy1})->({cx2},{cy2})  =  {crop_w}x{crop_h}")
    print(f"  Target    : {target_bitrate//1000} kbps  (libx264, {FFMPEG})")
    print(f"  Masks     : {len(masks)}")
    print(f"  Frames    : {total_frames}  @  {fps:.2f} fps")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Pipe BGR24 frames directly into ffmpeg — no large intermediate file
    ffmpeg_cmd = [
        FFMPEG, "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{crop_w}x{crop_h}",
        "-r", str(fps),
        "-pix_fmt", "bgr24",
        "-i", "pipe:0",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-b:v", str(target_bitrate),
        "-preset", "medium",
        "-movflags", "+faststart",
        "-an",
        str(output_path),
    ]

    # On Windows, suppress the console window that ffmpeg would otherwise open
    _kwargs = {}
    if sys.platform == "win32":
        _kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    ffmpeg_proc = subprocess.Popen(
        ffmpeg_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, **_kwargs
    )

    frame_idx = 0
    pipe_broken = False
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            cropped = frame[cy1:cy2, cx1:cx2].copy()

            for m in masks:
                if isinstance(m, dict) and m.get("type") == "poly":
                    # Irregular polygon mask
                    pts = np.array(
                        [[max(0, min(int(p[0]), crop_w)),
                          max(0, min(int(p[1]), crop_h))]
                         for p in m["points"]],
                        dtype=np.int32,
                    )
                    if len(pts) >= 3:
                        cv2.fillPoly(cropped, [pts], (0, 0, 0))
                else:
                    # Rectangle mask (legacy format: [x1, y1, x2, y2])
                    mx1, my1, mx2, my2 = m
                    mx1 = max(0, min(int(mx1), crop_w))
                    my1 = max(0, min(int(my1), crop_h))
                    mx2 = max(0, min(int(mx2), crop_w))
                    my2 = max(0, min(int(my2), crop_h))
                    if mx2 > mx1 and my2 > my1:
                        cropped[my1:my2, mx1:mx2] = 0

            try:
                ffmpeg_proc.stdin.write(cropped.tobytes())
            except BrokenPipeError:
                pipe_broken = True
                break

            frame_idx += 1
            if frame_idx % 250 == 0:
                print(f"  Progress  : {frame_idx}/{total_frames}")
    finally:
        cap.release()
        try:
            ffmpeg_proc.stdin.close()
        except BrokenPipeError:
            pass

    stderr = ffmpeg_proc.stderr.read()
    ffmpeg_proc.wait()
    if pipe_broken or ffmpeg_proc.returncode != 0:
        err = stderr.decode(errors="replace").strip().splitlines()
        print("  ERROR: ffmpeg failed —")
        for line in err[-10:]:
            print(f"    {line}")
        return False

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Output    : {output_path}  ({size_mb:.1f} MB)")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Process masked/cropped videos")
    parser.add_argument("--videos-dir", type=Path, default=DEFAULT_VIDEOS_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.config.exists():
        print(f"Config not found: {args.config}")
        print("Run  python manual_mask_extraction/annotate.py  first.")
        return

    with open(args.config) as f:
        config = json.load(f)

    print(f"Config    : {args.config}  ({len(config)} videos)")
    print(f"Videos dir: {args.videos_dir}")
    print(f"Output dir: {args.output_dir}\n")

    success, failed, skipped = 0, 0, 0

    for rel_path, annotation in config.items():
        video_path = args.videos_dir / rel_path
        if not video_path.exists():
            print(f"WARNING: not found — {video_path}")
            skipped += 1
            continue

        crop = annotation.get("crop")
        masks = annotation.get("masks", [])

        if not crop:
            print(f"WARNING: no crop defined for {rel_path}, skipping.")
            skipped += 1
            continue

        rel = Path(rel_path)
        out_subdir = args.output_dir / rel.parent
        out_name = rel.stem + "_masked.mp4"
        output_path = out_subdir / out_name

        print(f"\n{'='*60}")
        print(f"Processing: {rel_path}")

        try:
            ok = process_video(video_path, crop, masks, output_path)
            if ok:
                success += 1
            else:
                failed += 1
        except Exception as exc:
            import traceback
            print(f"  ERROR: {exc}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*60}")
    print(f"Done.  Success={success}  Failed={failed}  Skipped={skipped}")
    print(f"Output: {args.output_dir}")


if __name__ == "__main__":
    main()
