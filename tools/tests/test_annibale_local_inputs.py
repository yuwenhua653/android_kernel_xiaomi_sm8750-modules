import tempfile
import unittest
import os
from pathlib import Path

from check_annibale_local_inputs import blueprint_sources, resolve, check


class LocalInputsTests(unittest.TestCase):
    def test_comments_and_string_braces(self):
        refs, skipped = blueprint_sources('// src: "bad"\nx { src: "good}file", /* src: "bad" */ }')
        self.assertEqual(refs, [('src', 'good}file')])
        self.assertEqual(skipped, [])

    def test_module_and_computed_sources_are_not_files(self):
        refs, skipped = blueprint_sources('x { src: ":generated", srcs: common + ["a"], }')
        self.assertEqual(refs, [])
        self.assertEqual(len(skipped), 2)

    def test_literal_array(self):
        refs, _ = blueprint_sources('x { srcs: ["a", "b"], init_rc: ["service.rc"], }')
        self.assertEqual(refs, [('srcs', 'a'), ('srcs', 'b'), ('init_rc', 'service.rc')])

    def test_concatenated_scalar_is_not_partial_success(self):
        refs, skipped = blueprint_sources('x { src: "prefix" + variable, }')
        self.assertEqual(refs, [])
        self.assertEqual(len(skipped), 1)

    def test_missing_fstab_and_present_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(resolve(root, root, 'fstab.annibale-oss')[1], 'missing local source')
            (root/'fstab.annibale-oss').write_text('fstab')
            self.assertIsNone(resolve(root, root, 'fstab.annibale-oss')[1])

    def test_escape_and_empty_glob(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(resolve(root, root, '../outside')[1], 'source escapes checked tree')
            self.assertEqual(resolve(root, root, 'src/**/*.kt')[1], 'missing local source')
            (root/'bad').symlink_to('/etc/passwd')
            self.assertEqual(resolve(root, root, 'bad')[1], 'source escapes checked tree')


@unittest.skipUnless(os.environ.get('ANNIBALE_TEST_BPFMT'), 'real bpfmt fixture required')
class BlueprintParserTests(unittest.TestCase):
    def test_real_parser_and_missing_fstab(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'Android.bp').write_text('prebuilt_etc { name: "fstab", src: "fstab", }\n')
            tool = Path(os.environ['ANNIBALE_TEST_BPFMT'])
            before = check(root, tool)
            self.assertEqual(before['blueprints_parsed'], ['Android.bp'])
            self.assertEqual(before['errors'][0]['reason'], 'missing local source')
            (root/'fstab').write_text('data')
            self.assertEqual(check(root, tool)['status'], 'scoped_local_inputs_passed')

    def test_real_parser_rejects_malformed_blueprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'Android.bp').write_text('prebuilt_etc { name: [ }')
            result = check(root, Path(os.environ['ANNIBALE_TEST_BPFMT']))
            self.assertEqual(result['errors'][0]['reason'], 'Blueprint parse failed')

    def test_generated_module_is_explicitly_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'Android.bp').write_text('prebuilt_etc { name: "x", src: ":generated", }')
            result = check(root, Path(os.environ['ANNIBALE_TEST_BPFMT']))
            self.assertFalse(result['full_rom_built'])
            self.assertEqual(result['unverified_references'][0]['reason'], 'module reference')


if __name__ == '__main__':
    unittest.main()
