import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "coverage_check", Path(__file__).parents[1] / "check_annibale_oss_coverage.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CoverageTests(unittest.TestCase):
    def test_variants_and_renamed_implementation_are_not_silently_waived(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "source.ko"
            path.write_bytes(b"fixture")
            source = {"modules": {name: {
                "path": str(path), "sha256": hashlib.sha256(b"fixture").hexdigest()
            } for name in ["same", "replacement"]}}
            result = module.coverage({"modules": [{"name": name} for name in
                ["same", "same", "original", "optional"]]}, source)
            self.assertEqual(result["stock_unique_names"], 3)
            self.assertEqual(result["same_name_covered"], ["same"])
            self.assertEqual(result["missing_same_name_source"], ["optional", "original"])
            self.assertFalse(result["module_name_coverage_complete"])

    def test_stale_or_missing_file_cannot_cover_a_module(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "source.ko"
            path.write_bytes(b"changed")
            source = {"modules": {"same": {"path": str(path), "sha256": "0" * 64},
                                  "absent": {"path": str(path) + ".absent", "sha256": "0" * 64}}}
            result = module.coverage({"modules": [{"name": "same"}, {"name": "absent"}]}, source)
            self.assertEqual(len(result["invalid_source_files"]), 2)
            self.assertEqual(result["same_name_covered"], [])

    def test_name_completion_never_certifies_flashing(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "source.ko"
            path.write_bytes(b"fixture")
            result = module.coverage({"modules": [{"name": "same"}]}, {
                "modules": {"same": {"path": str(path),
                "sha256": hashlib.sha256(b"fixture").hexdigest()}}})
            self.assertTrue(result["module_name_coverage_complete"])
            self.assertFalse(result["flash_ready"])

    def test_empty_inventory_does_not_pass(self):
        result = module.coverage({"modules": []}, {"modules": {}})
        self.assertFalse(result["module_name_coverage_complete"])
        self.assertFalse(result["flash_ready"])


if __name__ == "__main__":
    unittest.main()
