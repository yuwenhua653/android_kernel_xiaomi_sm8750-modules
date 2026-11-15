import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "build_annibale_touch.py"
SPEC = importlib.util.spec_from_file_location("build_touch", SCRIPT)
build_touch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_touch)


class BuildTouchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("kernel/Makefile", "out/include/generated/autoconf.h",
                     "out/include/config/kernel.release", "clang/clang"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        self.args = [str(SCRIPT), "--kernel", str(self.root / "kernel"),
                     "--kernel-out", str(self.root / "out"), "--clang-bin",
                     str(self.root / "clang"), "--output", str(self.root / "touch")]

    def call(self, args):
        with patch("sys.argv", args), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return build_touch.main()

    def test_objects_are_staged_and_do_not_run_modpost(self):
        with patch.object(build_touch.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertEqual(self.call(self.args), 0)
            command = run.call_args.args[0]
            self.assertEqual(command[-2:], ["xiaomi/xiaomi_touch.o",
                                            "goodix_9916k/goodix_core.o"])
            self.assertIn("CONFIG_TOUCHSCREEN_XIAOMI_ANNIBALE=m", command)
            stage = Path(next(arg[2:] for arg in command if arg.startswith("M=")))
            self.assertTrue((stage / "goodix_9916k/goodix_ts_core.c").is_file())
            self.assertIn(self.root / "touch", stage.parents)
            self.assertFalse(any("KBUILD_MODPOST_WARN" in arg for arg in command))

    def test_module_build_refuses_missing_symbol_versions(self):
        with patch.object(build_touch.subprocess, "run") as run:
            with self.assertRaises(SystemExit) as failure:
                self.call(self.args + ["--modules"])
            self.assertEqual(failure.exception.code, 2)
            run.assert_not_called()
            self.assertFalse((self.root / "touch").exists())

    def test_output_cannot_write_into_source_checkout(self):
        with patch.object(build_touch.subprocess, "run") as run:
            with self.assertRaises(SystemExit):
                self.call(self.args[:-1] + [str(self.root / "kernel/staging")])
            run.assert_not_called()
            self.assertFalse((self.root / "kernel/staging").exists())

    def test_compiler_failure_is_preserved(self):
        with patch.object(build_touch.subprocess, "run") as run:
            run.return_value.returncode = 2
            self.assertEqual(self.call(self.args), 2)

    def test_real_driver_abi_length_boundaries(self):
        header_dir = SCRIPT.parents[1] / "xiaomi/touch/annibale/xiaomi"
        binary = self.root / "touch_bounds"
        subprocess.run(["cc", "-std=c11", "-Wall", "-Werror", "-I", str(header_dir),
                        str(SCRIPT.parent / "tests/touch_bounds.c"), "-o", str(binary)],
                       check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
