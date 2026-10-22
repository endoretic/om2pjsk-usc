import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

from PIL import Image

from src.engines import ENGINE_PROFILES, default_engine_path
from src.scp_writer import build_scp


class BackgroundPackagingTests(unittest.TestCase):
    def build_package(self, directory, mode, target):
        source = Path(directory) / "backgrounds.osz"
        output = Path(directory) / "backgrounds.scp"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("audio.mp3", b"audio fixture")
            for index, color in enumerate(((255, 0, 128), (0, 255, 128))):
                image = io.BytesIO()
                Image.new("RGB", (16, 9), color).save(image, format="PNG")
                archive.writestr(f"background-{index}.png", image.getvalue())
                archive.writestr(f"chart-{index}.osu", f"""osu file format v14
[General]
AudioFilename: audio.mp3
Mode: 3
[Metadata]
Title: Background {index}
Artist: Test
Creator: Test
Version: Test {index}
[Difficulty]
CircleSize: 6
[Events]
0,0,"background-{index}.png",0,0
[TimingPoints]
0,500,4,2,0,100,1,0
[HitObjects]
42,192,1000,1,0,0:0:0:0:
128,192,1500,128,0,2500:0:0:0:0:
""")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(build_scp(str(source), str(default_engine_path(target)), str(output),
                                       background_mode=mode, target_engine=target), 0)
        return output

    def test_generated_backgrounds_keep_local_images_without_online_source(self):
        for target, profile in ENGINE_PROFILES.items():
            with self.subTest(target=target):
                self.check_generated_backgrounds(target, profile)

    def check_generated_backgrounds(self, target, profile):
        with tempfile.TemporaryDirectory() as directory:
            output = self.build_package(directory, "original", target)
            with zipfile.ZipFile(output) as archive:
                backgrounds = {}

                def check_items(value):
                    if isinstance(value, dict):
                        name = value.get("name", "")
                        if name.startswith(profile.level_prefix + "-bg-"):
                            self.assertNotIn("source", value, name)
                            self.assertNotIn("authorUser", value, name)
                            self.assertEqual(value, backgrounds.setdefault(name, value))
                            image = archive.read(value["image"]["url"].lstrip("/"))
                            with Image.open(io.BytesIO(image)) as loaded:
                                expected = (255, 0, 128) if value["title"].endswith("0") else (0, 255, 128)
                                self.assertEqual(loaded.getpixel((0, 0)), expected)
                        for child in value.values():
                            check_items(child)
                    elif isinstance(value, list):
                        for child in value:
                            check_items(child)

                # Check details, indexes, and copies embedded in level items.
                for path in archive.namelist():
                    if not path.startswith("sonolus/repository/"):
                        check_items(json.loads(archive.read(path)))
                self.assertEqual(len(backgrounds), 2)
                engine = json.loads(archive.read(f"sonolus/engines/{profile.item_name}"))["item"]
                self.assertTrue(engine["source"].startswith("https://"))
                self.assertEqual(engine["background"]["source"], engine["source"])

    def test_default_mode_retains_engine_background(self):
        for target, profile in ENGINE_PROFILES.items():
            with self.subTest(target=target):
                self.check_default_background(target, profile)

    def check_default_background(self, target, profile):
        with tempfile.TemporaryDirectory() as directory:
            output = self.build_package(directory, "default", target)
            with zipfile.ZipFile(output) as archive:
                levels = json.loads(archive.read("sonolus/levels/list"))["items"]
                self.assertEqual(len(levels), 2)
                for level in levels:
                    self.assertEqual(level["useBackground"], {"useDefault": True})
                self.assertFalse(any(path.startswith(f"sonolus/backgrounds/{profile.level_prefix}-bg-")
                                     for path in archive.namelist()))


if __name__ == "__main__":
    unittest.main()
