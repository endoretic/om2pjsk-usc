import gzip
import hashlib
import io
import json
import math
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from osu_mania_to_scp import main
from src.engines import ENGINE_PROFILES, default_engine_path, get_engine_profile
from src.scp_writer import build_merged_scp, build_scp
from tests.helpers import make_osz


class EngineTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engines = {}
        cls.schemas = {}
        for target, profile in ENGINE_PROFILES.items():
            with zipfile.ZipFile(default_engine_path(target)) as archive:
                engine = json.loads(archive.read(f"sonolus/engines/{profile.item_name}"))["item"]
                cls.engines[target] = engine
                cls.schemas[target] = {}
                for mode in ("playData", "watchData", "previewData"):
                    runtime = json.loads(gzip.decompress(archive.read(engine[mode]["url"].lstrip("/"))))
                    cls.schemas[target][mode] = {
                        archetype["name"]: {field["name"] for field in archetype["imports"]}
                        for archetype in runtime["archetypes"]
                    }

    def assert_repository(self, archive):
        paths = set(archive.namelist())
        self.assertEqual(len(paths), len(archive.namelist()))
        self.assertIsNone(archive.testzip())

        def check_refs(value):
            if isinstance(value, dict):
                if "hash" in value and "url" in value:
                    path = f"sonolus/repository/{value['hash']}"
                    self.assertEqual(value["url"], "/" + path)
                    self.assertIn(path, paths)
                for child in value.values():
                    check_refs(child)
            elif isinstance(value, list):
                for child in value:
                    check_refs(child)

        for path in paths:
            data = archive.read(path)
            if path.startswith("sonolus/repository/"):
                self.assertEqual(hashlib.sha1(data).hexdigest(), path.rsplit("/", 1)[1])
            else:
                check_refs(json.loads(data))

    def test_bundled_resources_are_self_contained(self):
        for target, profile in ENGINE_PROFILES.items():
            with self.subTest(target=target), zipfile.ZipFile(default_engine_path(target)) as archive:
                self.assert_repository(archive)
                engine = self.engines[target]
                self.assertEqual(engine["version"], 13)
                for kind in ("skin", "background", "effect", "particle"):
                    item = json.loads(archive.read(f"sonolus/{kind}s/{engine[kind]['name']}"))["item"]
                    self.assertEqual(item.keys(), engine[kind].keys())
                    for field, value in item.items():
                        if field == "configuration":
                            # Older packs contain equivalent JSON with different gzip headers.
                            actual = json.loads(gzip.decompress(archive.read(value["url"].lstrip("/"))))
                            embedded = json.loads(gzip.decompress(archive.read(engine[kind][field]["url"].lstrip("/"))))
                            self.assertEqual(actual, embedded)
                        else:
                            self.assertEqual(value, engine[kind][field])
                for resource in ("configuration", "playData", "watchData", "previewData", "tutorialData"):
                    json.loads(gzip.decompress(archive.read(engine[resource]["url"].lstrip("/"))))
                self.assertTrue(gzip.decompress(archive.read(engine["rom"]["url"].lstrip("/"))))

    def test_bundled_nextrush_records_upstream_revision(self):
        description = self.engines["nextrush"]["description"]
        self.assertIn("v2.16.3", description)
        self.assertIn("6d6dd372985cd35154282129b4031adc9874b615", description)

    def test_profiles_resolve_from_bundle_root(self):
        with patch.object(sys, "_MEIPASS", str(Path.cwd() / "fake-bundle"), create=True):
            for target, profile in ENGINE_PROFILES.items():
                self.assertEqual(default_engine_path(target), Path(sys._MEIPASS) / profile.filename)
        with self.assertRaises(ValueError):
            get_engine_profile("unknown")

    def assert_leveldata(self, data, target, key_count, tail_mode):
        entities = data["entities"]
        names = {entity["name"] for entity in entities}
        self.assertEqual(len(names), len(entities))
        self.assertEqual(data["bgmOffset"], 1)
        archetypes = {entity["archetype"] for entity in entities}
        for mode, schema in self.schemas[target].items():
            self.assertFalse(archetypes - schema.keys(), (target, mode, archetypes - schema.keys()))
        for entity in entities:
            fields = {field["name"] for field in entity["data"]}
            # Watch/preview intentionally ignore some play-only input fields.
            self.assertFalse(fields - self.schemas[target]["playData"][entity["archetype"]])
            for field in entity["data"]:
                if "ref" in field:
                    self.assertIn(field["ref"], names)
                else:
                    self.assertTrue(math.isfinite(field["value"]))
                    if field["name"] == "#BEAT":
                        self.assertGreaterEqual(field["value"], 0)

        for prefix in ("Normal", "Critical"):
            self.assertIn(prefix + "TapNote", archetypes)
            self.assertIn(prefix + "HeadTapNote", archetypes)
            if tail_mode != "none":
                self.assertIn(prefix + "Tail" + tail_mode.title() + "Note", archetypes)
        if tail_mode == "none":
            self.assertIn("AnchorNote", archetypes)
            self.assertFalse(any("Tail" in name for name in archetypes))

        heads = [entity for entity in entities if entity["archetype"].endswith("HeadTapNote")]
        head_fields = [{f["name"]: f.get("value", f.get("ref")) for f in entity["data"]} for entity in heads]
        self.assertEqual(len(heads), 2)
        for col, fields in enumerate(head_fields):
            self.assertAlmostEqual(fields["lane"], -6 + (col + 0.5) * 12 / key_count)
            self.assertAlmostEqual(fields["size"], 6 / key_count)
            self.assertAlmostEqual(fields["#BEAT"], 1.49)
        ticks = [entity for entity in entities if entity["archetype"] == "TransientHiddenTickNote"]
        tick_beats = [next(f["value"] for f in entity["data"] if f["name"] == "#BEAT") for entity in ticks]
        self.assertEqual(sorted(tick_beats), [1.5, 1.5, 2, 2, 2.5, 2.5])
        self.assertEqual(sum(e["archetype"] == "Connector" for e in entities), 2)
        self.assertIn("SimLine", archetypes)

    def test_all_tail_modes_and_key_counts_match_both_runtime_schemas(self):
        target_names = {}
        with tempfile.TemporaryDirectory() as directory:
            source = make_osz(Path(directory) / "test.osz")
            output = Path(directory) / "test.scp"
            for target, profile in ENGINE_PROFILES.items():
                for tail in ("release", "trace", "none"):
                    with self.subTest(target=target, tail=tail), redirect_stdout(io.StringIO()):
                        progress = []
                        status = build_scp(str(source), str(default_engine_path(target)), str(output),
                                           target_engine=target, tail_mode=tail, tinged_columns=True,
                                           progress_callback=lambda *args: progress.append(args))
                        self.assertEqual(status, 0)
                        self.assertEqual(progress[0][:2], (0, 3))
                        self.assertEqual(progress[-1][:2], (3, 3))
                        with zipfile.ZipFile(output) as archive:
                            self.assert_repository(archive)
                            levels = json.loads(archive.read("sonolus/levels/list"))["items"]
                            self.assertEqual(len(levels), 3)
                            target_names[target] = {level["name"] for level in levels}
                            for key_count, level in zip((4, 5, 6), levels):
                                self.assertTrue(level["name"].startswith(profile.level_prefix + "-"))
                                self.assertEqual(level["engine"], self.engines[target])
                                self.assertEqual(level["useBackground"], {"useDefault": True})
                                details = json.loads(archive.read(f"sonolus/levels/{level['name']}"))
                                self.assertEqual(details["item"], level)
                                self.assertTrue({"description", "actions", "hasCommunity", "leaderboards", "sections"} <= details.keys())
                                self.assertEqual(archive.read(level["bgm"]["url"].lstrip("/")), b"audio fixture (not for playback)")
                                data = json.loads(gzip.decompress(archive.read(level["data"]["url"].lstrip("/"))))
                                self.assert_leveldata(data, target, key_count, tail)
        self.assertFalse(target_names["nextrush"] & target_names["next-sekai"])

    def test_merge_handles_duplicate_difficulty_names(self):
        with tempfile.TemporaryDirectory() as directory:
            sources = [str(make_osz(Path(directory) / f"{name}.osz", keys=(6,))) for name in ("first", "second")]
            for target, profile in ENGINE_PROFILES.items():
                with self.subTest(target=target), redirect_stdout(io.StringIO()):
                    output = Path(directory) / f"{target}.scp"
                    self.assertEqual(build_merged_scp(sources, str(default_engine_path(target)), str(output),
                                                     target_engine=target, background_mode="original"), 0)
                    with zipfile.ZipFile(output) as archive:
                        levels = json.loads(archive.read("sonolus/levels/list"))["items"]
                        self.assertEqual(len(levels), 2)
                        self.assertEqual(len({level["name"] for level in levels}), 2)
                        self.assertEqual(len({level["useBackground"]["item"]["name"] for level in levels}), 2)
                        self.assertEqual(len({level["bgm"]["hash"] for level in levels}), 1)
                        self.assertTrue(all(level["engine"]["name"] == profile.item_name for level in levels))

    def test_wrong_engine_pack_is_rejected_without_overwriting_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = make_osz(Path(directory) / "test.osz", keys=(6,))
            output = Path(directory) / "test.scp"
            output.write_bytes(b"existing output")
            for target, other in (("nextrush", "next-sekai"), ("next-sekai", "nextrush")):
                with self.subTest(target=target), redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(build_scp(str(source), str(default_engine_path(other)), str(output),
                                               target_engine=target), 1)
                    self.assertIn(ENGINE_PROFILES[target].item_name, errors.getvalue())
                    self.assertEqual(output.read_bytes(), b"existing output")

    def test_cli_routes_single_batch_and_merge_to_selected_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = [str(make_osz(Path(directory) / name, keys=(6,))) for name in ("one.osz", "two.osz")]
            output = str(Path(directory) / "test.scp")
            for target in ENGINE_PROFILES:
                for mode, args, function, expected_calls in (
                    ("single", [first, "--out", output], "build_scp", 1),
                    ("batch", [first, second, "--out-dir", directory], "build_scp", 2),
                    ("merge", [first, second, "--out", output, "--merge"], "build_merged_scp", 1),
                ):
                    with self.subTest(target=target, mode=mode), patch(f"src.scp_writer.{function}", return_value=0) as build:
                        self.assertEqual(main(args + ["--target-engine", target]), 0)
                        self.assertEqual(build.call_count, expected_calls)
                        for call in build.call_args_list:
                            self.assertEqual(call.args[1], str(default_engine_path(target)))
                            self.assertEqual(call.kwargs["target_engine"], target)
                            self.assertEqual(call.kwargs["tail_mode"], "release")
            with patch("src.scp_writer.build_scp", return_value=0) as build:
                self.assertEqual(main([first, "--out", output]), 0)
                self.assertEqual(build.call_args.kwargs["target_engine"], "nextrush")


if __name__ == "__main__":
    unittest.main()
