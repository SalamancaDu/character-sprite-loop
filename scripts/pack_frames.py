"""Package reviewed transparent frames without redrawing or changing their alpha."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys

from PIL import Image, ImageChops, ImageDraw


def natural_key(path: Path) -> list:
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", path.name)]


def read_rgba(path: Path) -> Image.Image:
    with Image.open(path) as image:
        if image.format != "PNG":
            raise ValueError(f"Expected PNG input: {path}")
        if "A" not in image.getbands() and "transparency" not in image.info:
            raise ValueError(f"Input has no alpha/transparency: {path}")
        return image.convert("RGBA")


def canonical(frame: Image.Image) -> Image.Image:
    # Ignore RGB values of fully transparent pixels when comparing appearance.
    canvas = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    canvas.alpha_composite(frame)
    return canvas


def changed_pixels(first: Image.Image, second: Image.Image) -> int:
    channels = ImageChops.difference(canonical(first), canonical(second)).split()
    mask = channels[0]
    for channel in channels[1:]:
        mask = ImageChops.lighter(mask, channel)
    return sum(mask.histogram()[1:])


def integer_vector(value: object, length: int, context: str) -> list[int]:
    if not isinstance(value, list) or len(value) != length or any(type(n) is not int for n in value):
        raise ValueError(f"{context}: expected {length} integers")
    return value


def load_layout(sheet: Image.Image, path: Path, count: int) -> list[Image.Image]:
    try:
        layout = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot read layout {path}: {error}") from error
    if not isinstance(layout, dict):
        raise ValueError(f"Layout {path}: expected an object")
    canvas = integer_vector(layout.get("canvas"), 2, f"Layout {path} canvas")
    if min(canvas) <= 0:
        raise ValueError(f"Layout {path}: canvas dimensions must be positive")
    entries = layout.get("frames")
    if not isinstance(entries, list) or len(entries) != count:
        raise ValueError(f"Layout {path}: frames must contain exactly {count} entries")
    frames = []
    for i, entry in enumerate(entries, 1):
        context = f"Layout {path}, frame {i}"
        if not isinstance(entry, dict):
            raise ValueError(f"{context}: expected crop and paste fields")
        left, top, right, bottom = integer_vector(entry.get("crop"), 4, f"{context} crop")
        x, y = integer_vector(entry.get("paste"), 2, f"{context} paste")
        if not (0 <= left < right <= sheet.width and 0 <= top < bottom <= sheet.height):
            raise ValueError(f"{context}: crop must be nonempty and inside source {sheet.size}")
        if not (0 <= x and 0 <= y and x + right - left <= canvas[0] and y + bottom - top <= canvas[1]):
            raise ValueError(f"{context}: paste would clip the crop outside canvas {canvas}")
        frame = Image.new("RGBA", tuple(canvas), (0, 0, 0, 0))
        # No mask: copy all RGBA bytes, including partial alpha and hidden RGB.
        frame.paste(sheet.crop((left, top, right, bottom)), (x, y))
        frames.append(frame)
    return frames


def load_frames(args: argparse.Namespace) -> list[Image.Image]:
    layout = getattr(args, "layout", None)
    if layout and (not args.sheet or args.rows is not None):
        raise ValueError("--layout requires --sheet and cannot be combined with --rows")
    if args.frames_dir:
        source = Path(args.frames_dir).resolve()
        paths = sorted(source.glob("frame_*.png"), key=natural_key)
        if len(paths) != args.count:
            raise ValueError(f"Expected {args.count} frame_*.png files in {source}, found {len(paths)}")
        return [read_rgba(path) for path in paths]
    if layout:
        return load_layout(read_rgba(Path(args.sheet).resolve()), Path(layout).resolve(), args.count)
    if not args.columns or not args.rows:
        raise ValueError("Sheet input requires --columns and --rows")
    if args.columns * args.rows != args.count:
        raise ValueError("Sheet rows x columns must equal --count; inspect unused cells explicitly")
    sheet = read_rgba(Path(args.sheet).resolve())
    width, height = sheet.size
    if width % args.columns or height % args.rows:
        raise ValueError(f"Sheet {sheet.size} is not exactly divisible by the specified grid")
    cell_w, cell_h = width // args.columns, height // args.rows
    return [sheet.crop(((i % args.columns) * cell_w, (i // args.columns) * cell_h,
                        (i % args.columns + 1) * cell_w, (i // args.columns + 1) * cell_h))
            for i in range(args.count)]


def validate_frames(frames: list[Image.Image], require_distinct: bool) -> dict:
    if len(frames) < 2:
        raise ValueError("An animation requires at least two frames")
    width, height = frames[0].size
    facts = []
    hashes = []
    for i, frame in enumerate(frames, 1):
        if frame.size != (width, height):
            raise ValueError(f"Frame {i}: size {frame.size} differs from {(width, height)}")
        alpha = frame.getchannel("A")
        histogram = alpha.histogram()
        bounds = alpha.getbbox()
        if bounds is None:
            raise ValueError(f"Frame {i} is empty")
        if histogram[0] == 0:
            raise ValueError(f"Frame {i} has no fully transparent pixels")
        facts.append({"frame": i, "alpha_bounds": list(bounds),
                      "transparent_pixels": histogram[0],
                      "partial_alpha_pixels": sum(histogram[1:255]),
                      "touches_canvas_edge": bounds[0] == 0 or bounds[1] == 0
                      or bounds[2] == width or bounds[3] == height})
        hashes.append(hashlib.sha256(canonical(frame).tobytes()).hexdigest())
    unique_count = len(set(hashes))
    if unique_count == 1:
        raise ValueError("All frames look identical: this is a static image, not an animation")
    if require_distinct and unique_count != len(frames):
        raise ValueError(f"Expected distinct frames; found {unique_count} distinct of {len(frames)}")
    transitions = [changed_pixels(frames[i], frames[(i + 1) % len(frames)])
                   for i in range(len(frames))]
    return {"frame_count": len(frames), "size": [width, height],
            "distinct_frames": unique_count, "changed_pixels_to_next_including_wrap": transitions,
            "wrap_changed_fraction": round(transitions[-1] / (width * height), 6),
            "frames": facts,
            "visual_review_required": ["character identity and count", "interior holes",
                                       "action and contact", "last-to-first motion"]}


def verify_apng(path: Path, frames: list[Image.Image], frame_ms: int) -> dict:
    with Image.open(path) as animation:
        if animation.info.get("loop") != 0 or animation.size != frames[0].size:
            raise ValueError("APNG loop parameter or canvas mismatch")
        decoded = []
        elapsed = 0.0
        for i in range(animation.n_frames):
            animation.seek(i)
            duration = float(animation.info.get("duration", 0))
            decoded.append((elapsed, elapsed + duration, canonical(animation.convert("RGBA")).tobytes()))
            elapsed += duration
        if abs(elapsed - len(frames) * frame_ms) > 0.1:
            raise ValueError(f"APNG total duration mismatch: decoded {elapsed}ms")
        for i, frame in enumerate(frames):
            time_ms = i * frame_ms + 0.01
            sample = next((pixels for start, end, pixels in decoded if start <= time_ms < end), None)
            if sample != canonical(frame).tobytes():
                raise ValueError(f"Decoded APNG does not reproduce source frame {i + 1}")
        return {"apng_encoded_frames": len(decoded), "duration_ms": round(elapsed, 3),
                "loop": 0, "decoded_timeline_matches_source": True}


def write_preview(output: Path, count: int, digits: int, size: tuple[int, int], frame_ms: int) -> None:
    template_path = Path(__file__).resolve().parents[1] / "assets" / "preview.html"
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"Cannot read preview template {template_path}: {error}") from error
    data = {"frames": [f"frames/frame_{i + 1:0{digits}d}.png" for i in range(count)],
            "width": size[0], "height": size[1], "frameMs": frame_ms}
    (output / "preview.html").write_text(template.replace("__FRAME_DATA__", json.dumps(data)), encoding="utf-8")


def pack(args: argparse.Namespace) -> dict:
    for field in ("count", "frame_ms", "columns", "rows"):
        value = getattr(args, field, None)
        if value is not None and value <= 0:
            raise ValueError(f"--{field.replace('_', '-')} must be positive")
    frames = load_frames(args)
    report = validate_frames(frames, args.require_distinct)
    columns = args.columns or min(5, args.count)
    rows = math.ceil(args.count / columns)
    width, height = frames[0].size
    output = Path(args.output_dir).resolve()
    # A new directory prevents mixing old frames or overwriting previous deliveries.
    if output.exists():
        raise ValueError(f"Output already exists; choose a new version directory: {output}")
    output.mkdir(parents=True)
    frame_dir = output / "frames"
    frame_dir.mkdir()
    digits = max(2, len(str(len(frames))))
    sheet = Image.new("RGBA", (width * columns, height * rows), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        frame.save(frame_dir / f"frame_{i + 1:0{digits}d}.png")
        sheet.paste(frame, ((i % columns) * width, (i // columns) * height))
    sheet.save(output / "sprite-sheet.png")
    # Preview only: downscale the whole contact sheet while preserving source frames.
    preview = Image.new("RGBA", sheet.size, (255, 255, 255, 255))
    preview.alpha_composite(sheet)
    preview = preview.convert("RGB")
    factor = min(1.0, 2400 / max(preview.size))
    if factor < 1:
        preview = preview.resize((max(1, round(preview.width * factor)),
                                  max(1, round(preview.height * factor))), Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(preview)
    for i in range(len(frames)):
        x = round(((i % columns) * width + 4) * factor)
        y = round(((i // columns) * height + 4) * factor)
        draw.text((x, y), f"{i + 1:02d}", fill=(70, 70, 70), stroke_fill=(255, 255, 255), stroke_width=1)
    preview.save(output / "preview-white.png")
    animation_path = output / "loop.apng"
    frames[0].save(animation_path, format="PNG", save_all=True, append_images=frames[1:],
                   duration=args.frame_ms, loop=0, disposal=1, blend=0)
    report.update(verify_apng(animation_path, frames, args.frame_ms))
    shutil.make_archive(str(output / "frames"), "zip", root_dir=frame_dir)
    write_preview(output, len(frames), digits, (width, height), args.frame_ms)
    report.update({"output_dir": str(output), "frame_ms": args.frame_ms,
                   "note": "Numeric checks do not prove natural or seamless motion."})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--frames-dir", help="Directory containing only the intended frame_*.png set")
    source.add_argument("--sheet", help="Reviewed transparent PNG sprite sheet")
    parser.add_argument("--layout", help="JSON crop/paste layout for --sheet; incompatible with --rows")
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--columns", type=int, help="Output columns; also input columns for equal-grid sheets")
    parser.add_argument("--rows", type=int)
    parser.add_argument("--frame-ms", type=int, default=100)
    parser.add_argument("--require-distinct", action="store_true")
    parser.add_argument("--output-dir", required=True, help="Must be a new directory")
    args = parser.parse_args()
    try:
        print(json.dumps(pack(args), ensure_ascii=True, indent=2))
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
