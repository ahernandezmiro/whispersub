import json
import os
import tempfile
import unittest

from src.cache import build_manifest, cache_is_valid, write_manifest
from src.utils import temp_dir


class CacheTests(unittest.TestCase):
    def test_manifest_invalidates_when_source_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "video.mkv")
            artifact = os.path.join(directory, "audio.wav")
            with open(source, "wb") as handle:
                handle.write(b"first")
            with open(artifact, "wb") as handle:
                handle.write(b"audio")
            manifest = build_manifest("audio", source, {"rate": 16000})
            write_manifest(artifact, manifest)
            self.assertTrue(cache_is_valid(artifact, manifest))

            with open(source, "ab") as handle:
                handle.write(b"changed")
            changed = build_manifest("audio", source, {"rate": 16000})
            self.assertFalse(cache_is_valid(artifact, changed))

    def test_manifest_is_json(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "video.mkv")
            artifact = os.path.join(directory, "audio.wav")
            open(source, "wb").close()
            open(artifact, "wb").close()
            write_manifest(artifact, build_manifest("audio", source, {}))
            with open(f"{artifact}.manifest.json", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["stage"], "audio")

    def test_same_basename_in_different_paths_uses_different_directories(self):
        first = temp_dir("episode", os.path.join("one", "episode.mkv"))
        second = temp_dir("episode", os.path.join("two", "episode.mkv"))
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
