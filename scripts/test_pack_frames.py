"""Regression checks using synthetic RGBA fixtures and optional existing source frames."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from PIL import Image

import pack_frames as packer


class PackFramesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sprite-pack-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        reference = Image.new("RGBA", (24, 32), (0, 0, 0, 0))
        reference.paste((255, 190, 35, 255), (4, 3, 20, 25))
        reference.paste((255, 255, 255, 255), (7, 6, 11, 10))
        reference.paste((0, 0, 0, 0), (10, 15, 14, 20))
        reference.putpixel((3, 3), (255, 190, 35, 110))
        size = (reference.width + 12, reference.height + 12)
        self.frames = []
        self.source = self.root / "source"
        self.source.mkdir()
        for i, position in enumerate(((0, 0), (7, 3)), 1):
            frame = Image.new("RGBA", size, (0, 0, 0, 0))
            frame.paste(reference, position)
            # Fixture probes for exact copying of hidden RGB and partial alpha.
            frame.putpixel((size[0] - 1, size[1] - 1), (57, 83, 112, 0))
            frame.putpixel((size[0] - 2, size[1] - 1), (17, 31, 47, 119))
            frame.save(self.source / f"frame_{i:02d}.png")
            self.frames.append(frame)

    def args(self, **updates):
        values = dict(frames_dir=str(self.source), sheet=None, layout=None, count=2,
                      columns=2, rows=None, frame_ms=60, require_distinct=True,
                      output_dir=str(self.root / "output"))
        values.update(updates)
        return argparse.Namespace(**values)

    def assert_pixels(self, actual, expected):
        self.assertEqual(actual.size, expected.size)
        self.assertEqual(actual.tobytes(), expected.tobytes())

    def layout_fixture(self):
        width, height = self.frames[0].size
        sheet = Image.new("RGBA", (width * 2 + 33, height + 23), (0, 0, 0, 0))
        sheet.paste(self.frames[0], (3, 5))
        sheet.paste(self.frames[1], (width + 21, 11))
        sheet_path = self.root / "uneven.png"
        sheet.save(sheet_path)
        layout = {"canvas": [width + 18, height + 16], "frames": [
            {"crop": [width + 21, 11, width * 2 + 21, height + 11], "paste": [5, 6]},
            {"crop": [3, 5, width + 3, height + 5], "paste": [11, 3]},
        ]}
        path = self.root / "layout.json"
        path.write_text(json.dumps(layout), encoding="utf-8")
        return sheet_path, path, layout

    def test_independent_frames_png_zip_apng_and_sheet(self):
        report = packer.pack(self.args())
        output = self.root / "output"
        self.assertTrue(report["decoded_timeline_matches_source"])
        self.assertEqual(report["duration_ms"], 120)
        sheet = packer.read_rgba(output / "sprite-sheet.png")
        width, height = self.frames[0].size
        with zipfile.ZipFile(output / "frames.zip") as archive:
            self.assertEqual(archive.testzip(), None)
            self.assertEqual(len(archive.namelist()), 2)
            for i, expected in enumerate(self.frames, 1):
                name = f"frame_{i:02d}.png"
                path = output / "frames" / name
                self.assert_pixels(packer.read_rgba(path), expected)
                self.assertEqual(archive.read(name), path.read_bytes())
                self.assert_pixels(sheet.crop(((i - 1) * width, 0, i * width, height)), expected)

    def test_layout_preserves_order_placement_and_rgba(self):
        sheet, path, layout = self.layout_fixture()
        report = packer.pack(self.args(frames_dir=None, sheet=str(sheet), layout=str(path), columns=1))
        self.assertEqual(report["size"], layout["canvas"])
        for i, source_index in enumerate((1, 0), 1):
            expected = Image.new("RGBA", tuple(layout["canvas"]), (0, 0, 0, 0))
            expected.paste(self.frames[source_index], tuple(layout["frames"][i - 1]["paste"]))
            self.assert_pixels(packer.read_rgba(self.root / "output" / "frames" / f"frame_{i:02d}.png"), expected)
        with Image.open(self.root / "output" / "sprite-sheet.png") as result:
            self.assertEqual(result.size, (layout["canvas"][0], layout["canvas"][1] * 2))

    def test_layout_rejects_invalid_coordinates_count_and_shape_before_output(self):
        sheet, path, layout = self.layout_fixture()
        bad_layouts = [[], {}, {**layout, "canvas": [0, 10]}, {**layout, "frames": layout["frames"][:1]}]
        for key, value in (("crop", [-1, 0, 1, 1]), ("crop", [0, 0, 99999, 1]),
                           ("crop", [5, 5, 5, 6]), ("crop", [0, 0, 1.5, 2]),
                           ("crop", [False, 0, 1, 2]), ("paste", [-1, 0]),
                           ("paste", [99999, 0]), ("paste", [0])):
            bad = copy.deepcopy(layout)
            bad["frames"][0][key] = value
            bad_layouts.append(bad)
        for bad in bad_layouts:
            with self.subTest(layout=bad):
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(ValueError):
                    packer.pack(self.args(frames_dir=None, sheet=str(sheet), layout=str(path)))
                self.assertFalse((self.root / "output").exists())

    def test_layout_invalid_json_and_missing_file_have_context(self):
        sheet, path, _ = self.layout_fixture()
        for invalid in (True, False):
            if invalid:
                path.write_text("{broken", encoding="utf-8")
            else:
                path.unlink()
            with self.assertRaisesRegex(ValueError, "Cannot read layout"):
                packer.pack(self.args(frames_dir=None, sheet=str(sheet), layout=str(path)))

    def test_layout_argument_conflicts(self):
        sheet, path, _ = self.layout_fixture()
        for args in (self.args(layout=str(path)),
                     self.args(frames_dir=None, sheet=str(sheet), layout=str(path), rows=1)):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "--layout requires --sheet"):
                packer.pack(args)
        result = subprocess.run([sys.executable, "-B", str(Path(packer.__file__)),
                                 "--frames-dir", str(self.source), "--layout", str(path), "--count", "2",
                                 "--output-dir", str(self.root / "output")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("--layout requires --sheet", result.stderr)

    def test_equal_grid_preserves_order(self):
        width, height = self.frames[0].size
        sheet = Image.new("RGBA", (2 * width, height), (0, 0, 0, 0))
        for i, frame in enumerate(self.frames):
            sheet.paste(frame, (i * width, 0))
        path = self.root / "grid.png"
        sheet.save(path)
        packer.pack(self.args(frames_dir=None, sheet=str(path), rows=1))
        for i, expected in enumerate(self.frames, 1):
            self.assert_pixels(packer.read_rgba(self.root / "output" / "frames" / f"frame_{i:02d}.png"), expected)

    def test_grid_does_not_discard_remainder_or_extra_cells(self):
        sheet, _, _ = self.layout_fixture()
        for rows, count, message in ((1, 2, "not exactly divisible"), (2, 2, "must equal")):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, message):
                packer.pack(self.args(frames_dir=None, sheet=str(sheet), rows=rows, count=count))
            self.assertFalse((self.root / "output").exists())

    def test_existing_output_is_not_overwritten(self):
        output = self.root / "output"
        output.mkdir()
        sentinel = output / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Output already exists"):
            packer.pack(self.args())
        self.assertEqual(list(output.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_text(), "keep")

    def test_rejects_empty_opaque_different_size_and_static(self):
        probes = [(Image.new("RGBA", self.frames[0].size), "empty"),
                  (Image.new("RGBA", self.frames[0].size, "white"), "no fully transparent"),
                  (Image.new("RGBA", (1, 1)), "differs")]
        for bad, message in probes:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                packer.validate_frames([self.frames[0], bad], False)
        hidden_change = self.frames[0].copy()
        hidden_change.putpixel((hidden_change.width - 1, hidden_change.height - 1), (1, 2, 3, 0))
        with self.assertRaisesRegex(ValueError, "All frames look identical"):
            packer.validate_frames([self.frames[0], hidden_change], False)

    def test_intentional_hold_retains_apng_timeline(self):
        self.frames[1].save(self.source / "frame_03.png")
        report = packer.pack(self.args(count=3, require_distinct=False))
        self.assertEqual(report["duration_ms"], 180)
        self.assertTrue(report["decoded_timeline_matches_source"])
        with self.assertRaisesRegex(ValueError, "Expected distinct"):
            packer.validate_frames([self.frames[0], self.frames[1], self.frames[1]], True)

    def test_preview_contains_local_frames_and_original_timing(self):
        packer.pack(self.args())
        html = (self.root / "output" / "preview.html").read_text(encoding="utf-8")
        payload = html.split('<script id="frame-data" type="application/json">', 1)[1].split("</script>", 1)[0]
        data = json.loads(payload)
        self.assertEqual(data["frameMs"], 60)
        self.assertEqual(data["frames"], ["frames/frame_01.png", "frames/frame_02.png"])
        for name in data["frames"]:
            self.assertTrue((self.root / "output" / name).is_file())
        self.assertNotIn("__FRAME_DATA__", html)

    def test_25_frame_timeline(self):
        if os.environ.get("SPRITE_TEST_FRAMES"):
            source = Path(os.environ["SPRITE_TEST_FRAMES"])
        else:
            source = self.root / "timeline-source"
            source.mkdir()
            for i in range(25):
                frame = Image.new("RGBA", (self.frames[0].width + 25, self.frames[0].height), (0, 0, 0, 0))
                frame.paste(self.frames[0], (i, 0))
                frame.save(source / f"frame_{i + 1:02d}.png")
        expected = [packer.read_rgba(p) for p in sorted(source.glob("frame_*.png"), key=packer.natural_key)]
        self.assertEqual(len(expected), 25)
        report = packer.pack(self.args(frames_dir=str(source), count=25, columns=5))
        self.assertEqual(report["duration_ms"], 1500)
        self.assertTrue(report["decoded_timeline_matches_source"])
        with zipfile.ZipFile(self.root / "output" / "frames.zip") as archive:
            self.assertEqual(len(archive.namelist()), 25)
            for i, frame in enumerate(expected, 1):
                name = f"frame_{i:02d}.png"
                path = self.root / "output" / "frames" / name
                self.assert_pixels(packer.read_rgba(path), frame)
                self.assertEqual(archive.read(name), path.read_bytes())


if __name__ == "__main__":
    unittest.main()
