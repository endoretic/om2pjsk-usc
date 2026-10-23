import gzip
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from src.engines import ENGINE_PROFILES, default_engine_path
from src.osu_parser import parse_osu
from src.scp_writer import build_scp
from tests.helpers import make_osz


class OptionalOszResourceTests(unittest.TestCase):
    def test_missing_audio_chart_is_skipped_for_both_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            source = make_osz(Path(directory) / "mixed.osz", keys=(6,))
            with zipfile.ZipFile(source, "a") as archive:
                text = archive.read("6K.osu").decode()
                archive.writestr("missing.osu", text.replace("Version: 6K", "Version: missing")
                                 .replace("AudioFilename: audio.mp3", "AudioFilename: absent.mp3"))
                archive.writestr("empty.osu", text.replace("Version: 6K", "Version: empty")
                                 .replace("AudioFilename: audio.mp3", "AudioFilename: empty.mp3"))
                archive.writestr("empty.mp3", b"")
            for target in ENGINE_PROFILES:
                with self.subTest(target=target):
                    output = Path(directory) / f"{target}.scp"
                    messages = []
                    errors = io.StringIO()
                    with redirect_stdout(io.StringIO()), redirect_stderr(errors):
                        status = build_scp(str(source), str(default_engine_path(target)), str(output),
                                           target_engine=target, background_mode="original",
                                           progress_callback=lambda current, total, message: messages.append(message))
                    self.assertEqual(status, 0)
                    self.assertIn("Skipped missing", errors.getvalue())
                    self.assertIn("Skipped empty", errors.getvalue())
                    self.assertTrue(any("Skipped missing" in message for message in messages))
                    self.assertTrue(any("Skipped empty" in message for message in messages))
                    self.assertIn("1 levels, 2 skipped", messages[-1])
                    with zipfile.ZipFile(output) as archive:
                        levels = json.loads(archive.read("sonolus/levels/list"))["items"]
                        self.assertEqual(len(levels), 1)
                        for field in ("bgm", "preview"):
                            resource = levels[0][field]
                            self.assertTrue(resource["hash"])
                            blob = archive.read(resource["url"].lstrip("/"))
                            self.assertEqual(hashlib.sha1(blob).hexdigest(), resource["hash"])
                        self.assertEqual(len([name for name in archive.namelist()
                                              if name.startswith("sonolus/levels/")
                                              and name not in ("sonolus/levels/info", "sonolus/levels/list")]), 1)

    def test_all_missing_audio_fails_without_creating_or_overwriting_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = make_osz(Path(directory) / "missing.osz", keys=(6,))
            with zipfile.ZipFile(source, "a") as archive:
                text = archive.read("6K.osu").decode()
                archive.writestr("missing.osu", text.replace("Version: 6K", "Version: missing")
                                 .replace("AudioFilename: audio.mp3", "AudioFilename: absent.mp3"))
            for target in ENGINE_PROFILES:
                for existing in (False, True):
                    with self.subTest(target=target, existing=existing):
                        output = Path(directory) / f"{target}-{existing}.scp"
                        if existing:
                            output.write_bytes(b"preserve existing file")
                        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                            status = build_scp(str(source), str(default_engine_path(target)), str(output),
                                               single_version="missing", target_engine=target)
                        self.assertEqual(status, 1)
                        if existing:
                            self.assertEqual(output.read_bytes(), b"preserve existing file")
                        else:
                            self.assertFalse(output.exists())

    def test_video_and_storyboard_do_not_change_exported_chart_or_add_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            source = make_osz(Path(directory) / "media.osz", keys=(6,))
            with zipfile.ZipFile(source) as archive:
                base = {name: archive.read(name) for name in archive.namelist()}
            baseline_chart = parse_osu(base["6K.osu"].decode())
            events = (
                'Video,-2135,"optional.mp4"\n'
                'Sprite,Background,Centre,"storyboard-only.png",320,240\n'
                ' F,0,0,1000,0,1\n'
                'Animation,Foreground,Centre,"missing-frame.png",320,240,5,100,LoopForever\n'
            )
            video = b"video fixture, never exported"
            storyboard = b'[Events]\nSprite,Background,Centre,"missing.png",320,240\n'
            for present in (False, True):
                changed = dict(base)
                changed["6K.osu"] = base["6K.osu"].replace(b"[TimingPoints]", events.encode() + b"[TimingPoints]")
                changed["storyboard.osb"] = storyboard
                if present:
                    changed["optional.mp4"] = video
                self.assertEqual(parse_osu(changed["6K.osu"].decode()), baseline_chart)
                with zipfile.ZipFile(source, "w") as archive:
                    for name, data in changed.items():
                        archive.writestr(name, data)
                for target in ENGINE_PROFILES:
                    with self.subTest(target=target, video_present=present):
                        output = Path(directory) / f"{target}-{present}.scp"
                        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                            status = build_scp(str(source), str(default_engine_path(target)), str(output),
                                               target_engine=target, background_mode="original")
                        self.assertEqual(status, 0)
                        with zipfile.ZipFile(output) as archive:
                            for ignored in (video, storyboard):
                                self.assertNotIn("sonolus/repository/" + hashlib.sha1(ignored).hexdigest(),
                                                 archive.namelist())
                            level = json.loads(archive.read("sonolus/levels/list"))["items"][0]
                            self.assertFalse(level["useBackground"]["useDefault"])
                            bg = level["useBackground"]["item"]
                            self.assertTrue(archive.read(bg["image"]["url"].lstrip("/")).startswith(b"\x89PNG"))
                            data = gzip.decompress(archive.read(level["data"]["url"].lstrip("/")))
                            if not present:
                                baseline = Path(directory) / f"{target}.leveldata"
                                baseline.write_bytes(data)
                            else:
                                self.assertEqual(data, (Path(directory) / f"{target}.leveldata").read_bytes())


if __name__ == "__main__":
    unittest.main()
