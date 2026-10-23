import copy
import gzip
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / ".github" / "skills" /
          "nextrush-upstream-sync" / "scripts" / "repack_engine_scp.py")
SPEC = importlib.util.spec_from_file_location("repack_engine_scp", SCRIPT)
repack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repack)


class EngineRepackTests(unittest.TestCase):
    def make_fixture(self):
        old_skin = {"name": "default-skin", "source": "https://example.com",
                    "data": {"hash": "old-data"}, "texture": {"hash": "old-texture"}}
        engine = {"name": "NextRUSH_P", "skin": old_skin,
                  "playData": {"hash": "keep-runtime"}, "background": {"name": "keep-background"}}
        entries = {
            "sonolus/skins/default-skin": repack.json_dump({"item": old_skin}),
            "sonolus/skins/list": repack.json_dump({"items": [old_skin]}),
            "sonolus/skins/info": repack.json_dump({"sections": [{"itemType": "skin", "items": [old_skin]}]}),
            "sonolus/repository/keep-runtime": b"unchanged runtime",
        }
        skin = {"name": "default-skin", "source": "https://example.com"}
        resources = {}
        for field, data in (("thumbnail", b"thumbnail"), ("texture", b"new texture"),
                            ("data", gzip.compress(b'{"sprites":[]}'))):
            digest = repack.hash_bytes(data)
            skin[field] = {"hash": digest, "url": f"https://example.com/sonolus/repository/{digest}"}
            resources[f"sonolus/repository/{digest}"] = data
        return entries, engine, skin, resources

    def write_source(self, directory, skin, resources):
        path = Path(directory) / "source.scp"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("sonolus/skins/default-skin", repack.json_dump({"item": skin}))
            archive.writestr("sonolus/engines/NextRUSH_P", b"must not import online engine")
            for name, data in resources.items():
                archive.writestr(name, data)
        return path

    def test_refresh_updates_skin_references_without_replacing_runtime(self):
        entries, engine, skin, resources = self.make_fixture()
        before_engine = copy.deepcopy(engine)
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory, skin, resources)
            obsolete = repack.refresh_default_skin(entries, engine, source)
        self.assertEqual(obsolete, {"old-data", "old-texture"})
        self.assertEqual(engine["playData"], before_engine["playData"])
        self.assertEqual(engine["background"], before_engine["background"])
        self.assertEqual(entries["sonolus/repository/keep-runtime"], b"unchanged runtime")
        self.assertNotIn("sonolus/engines/NextRUSH_P", entries)
        self.assertEqual(json.loads(entries["sonolus/skins/default-skin"])["item"], engine["skin"])
        self.assertEqual(json.loads(entries["sonolus/skins/list"])["items"], [engine["skin"]])
        self.assertEqual(json.loads(entries["sonolus/skins/info"])["sections"][0]["items"], [engine["skin"]])
        for field in ("thumbnail", "data", "texture"):
            resource = engine["skin"][field]
            self.assertEqual(resource["url"], f"/sonolus/repository/{resource['hash']}")
            self.assertEqual(repack.hash_bytes(entries[resource["url"].lstrip("/")]), resource["hash"])

    def test_refresh_rejects_different_skin_identity_before_mutating(self):
        for field in ("name", "source"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                entries, engine, skin, resources = self.make_fixture()
                before = copy.deepcopy((entries, engine))
                skin[field] = "different"
                source = self.write_source(directory, skin, resources)
                with self.assertRaisesRegex(ValueError, "same name and source"):
                    repack.refresh_default_skin(entries, engine, source)
                self.assertEqual((entries, engine), before)

    def test_refresh_rejects_corrupt_resource_before_mutating(self):
        entries, engine, skin, resources = self.make_fixture()
        before = copy.deepcopy((entries, engine))
        resources[f"sonolus/repository/{skin['texture']['hash']}"] = b"corrupt texture"
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory, skin, resources)
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                repack.refresh_default_skin(entries, engine, source)
        self.assertEqual((entries, engine), before)


if __name__ == "__main__":
    unittest.main()
