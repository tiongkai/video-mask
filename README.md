# Quickstart

## Manual Mask Extraction

Crop videos to a region of interest and black out specific areas with hand-drawn shapes. No AI involved — fast and deterministic. Supports both rectangles and irregular polygons.

Set up the environment by running:

`conda create -n video-mask python=3.9`

`conda activate video-mask`

`pip install -r requirements.txt`

### Step 1 — Annotate

```bash
python manual_mask_extraction/annotate.py [--videos-dir DIR] [--videos A.mp4 ...]
```

**Phase 1 — Crop region**

Scrub through the video to find the right frame before confirming your crop.

| Key | Action |
| --- | ------ |
| Left-drag | Draw crop rectangle |
| `←` / `→` | Step ±1 frame |
| `,` / `.` | Step ±30 frames |
| `<` / `>` | Jump ±10% of total duration |
| `Enter` | Confirm crop |
| `R` | Reset current crop |
| `S` | Skip this video |
| `Q` | Save config and quit |

**Phase 2 — Mask shapes** (drawn on the cropped view)

Two modes: **RECT** (default) and **POLY**. Switch with `P`.

| Key | Action |
| --- | ------ |
| Left-drag | Draw rectangular mask [RECT mode] |
| `Enter` | Add the pending rectangle [RECT mode] |
| `P` | Switch to polygon mode |
| Left-click | Add a polygon vertex [POLY mode] |
| `Enter` | Confirm polygon (≥ 3 vertices required) [POLY mode] |
| `Z` | Undo last polygon vertex [POLY mode] |
| `R` | Cancel current polygon, return to rect mode |
| `U` | Undo last confirmed mask (any type) |
| `N` | Done with this video, move to next |
| `Q` | Save config and quit |

While drawing a polygon the display shows a rubber-band line to the cursor and a faint closing-line preview. Confirmed masks are shown with a semi-transparent fill.

Config saved to `manual_mask_extraction/config.json`. Re-run at any time to edit existing annotations.

### Step 2 — Process

```bash
python manual_mask_extraction/process.py [--videos-dir DIR] [--output-dir DIR]
```

Produces cropped + blacked-out videos in `manual_mask_extraction/outputs/`. Rectangles are applied with array slicing; polygons use `cv2.fillPoly`. Encodes with `libx264` at a bitrate proportional to the crop area (always smaller than the original), `yuv420p` pixel format for broad player compatibility. Old rectangle-only configs remain fully compatible.
