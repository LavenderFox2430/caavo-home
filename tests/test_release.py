"""The public checkout must build without private device evidence."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def test_clean_checkout_build_is_reproducible_and_contains_only_public_files(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            shutil.copytree(
                ROOT / "custom_components",
                checkout / "custom_components",
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            (checkout / "tools").mkdir()
            for filename in ("README.md", "LICENSE", "hacs.json", "tools/build_release.py"):
                shutil.copy2(ROOT / filename, checkout / filename)

            def build():
                subprocess.run(
                    [sys.executable, str(checkout / "tools/build_release.py")],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return json.loads((checkout / "dist/release.json").read_text())

            receipt = build()
            archive = checkout / "dist" / receipt["file"]
            first = archive.read_bytes()
            self.assertEqual(receipt["sha256"], hashlib.sha256(first).hexdigest())
            self.assertFalse(receipt["includes_device_captures"])
            self.assertFalse((checkout / "tests/evidence").exists())
            with zipfile.ZipFile(archive) as package:
                names = set(package.namelist())
                expected = {
                    path.relative_to(checkout).as_posix()
                    for path in (checkout / "custom_components").rglob("*")
                    if path.is_file()
                } | {"INSTALL_CAAVO_HOME.md", "LICENSE_CAAVO_HOME.txt"}
                self.assertEqual(names, expected)
                self.assertIn("custom_components/caavo_home/manifest.json", names)
                manifest = json.loads(package.read("custom_components/caavo_home/manifest.json"))
                self.assertEqual(manifest["version"], receipt["version"])
                self.assertEqual(manifest["codeowners"], ["@LavenderFox2430"])
                self.assertIsNone(package.testzip())
            self.assertEqual(build()["sha256"], receipt["sha256"])
            self.assertEqual(archive.read_bytes(), first)
