#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise pinned tool acquisition against a real local Git remote."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "ci_annibale_arm64.py"
SPEC = importlib.util.spec_from_file_location("ci_annibale_arm64", SOURCE)
CI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CI)


class ToolchainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="annibale tools ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "remote"
        self.repo.mkdir()
        self.git("init", "--quiet")
        self.git("config", "user.name", "Toolchain Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "uploadpack.allowFilter", "true")
        (self.repo / "common/bison").mkdir(parents=True)
        (self.repo / "unselected").mkdir()
        (self.repo / "common/bison/skeleton.m4").write_bytes(b"reviewed content\n")
        (self.repo / "unselected/unused").write_bytes(b"not needed\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "reviewed tools")
        self.commit = self.git("rev-parse", "HEAD").strip()
        (self.repo / "common/bison/skeleton.m4").write_bytes(b"later unreviewed content\n")
        self.git("commit", "--quiet", "-am", "new branch tip")
        self.spec = {"name": "bison-data", "repo": self.repo.as_uri(),
                     "revision": self.commit, "subdir": "common/bison"}
        self.tools = self.root / "tools"
        self.tools.mkdir()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True)

    def test_uses_pinned_content_not_moving_branch(self):
        path = CI.toolchain(self.tools, self.spec)
        self.assertEqual((path / "skeleton.m4").read_bytes(), b"reviewed content\n")
        self.assertFalse((self.tools / "bison-data/unselected").exists())

    def test_checkout_retry_retains_pinned_content(self):
        original = CI.run
        interruptions = []
        def interrupted(command, **kwargs):
            if "checkout" in command and not interruptions:
                interruptions.append(command)
                raise subprocess.CalledProcessError(128, command)
            return original(command, **kwargs)
        with patch.object(CI, "run", side_effect=interrupted), patch.object(CI.time, "sleep"):
            path = CI.toolchain(self.tools, self.spec)
        self.assertEqual(len(interruptions), 1)
        self.assertEqual((path / "skeleton.m4").read_bytes(), b"reviewed content\n")

    def test_transfer_stops_after_three_failures(self):
        command = ["git", "fetch", "unavailable"]
        with patch.object(CI, "run", side_effect=subprocess.CalledProcessError(128, command)) as run:
            with patch.object(CI.time, "sleep"):
                with self.assertRaises(subprocess.CalledProcessError):
                    CI.transfer(command, timeout=10)
        self.assertEqual(run.call_count, 3)

    def test_rejects_missing_subtree(self):
        self.spec["subdir"] = "does-not-exist"
        with self.assertRaisesRegex(ValueError, "missing/invalid"):
            CI.toolchain(self.tools, self.spec)

    def test_rejects_moving_ref_and_path_escape(self):
        self.spec["revision"] = "main"
        with self.assertRaisesRegex(ValueError, "full commit"):
            CI.toolchain(self.tools, self.spec)
        self.spec["revision"] = self.commit
        self.spec["subdir"] = "../outside"
        with self.assertRaisesRegex(ValueError, "relative"):
            CI.toolchain(self.tools, self.spec)


if __name__ == "__main__":
    unittest.main()
