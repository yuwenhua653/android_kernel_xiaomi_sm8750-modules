# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_annibale_vendor_blobs import audit, parse_list, deduplicate_entries


class VendorBlobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for part in ('vendor', 'odm'):
            (self.root / part / 'lib64').mkdir(parents=True)
        (self.root / 'odm/lib64/libreal.so').write_bytes(b'blob')

    def test_remap_uses_source_and_preserves_fixup(self):
        report = audit(self.root, '-odm/lib64/libreal.so:vendor/lib64/renamed.so;FIX_SONAME')
        item = report['entries'][0]
        self.assertEqual(item['status'], 'present')
        self.assertEqual(item['destination'], 'vendor/lib64/renamed.so')
        self.assertEqual(item['flags'], ['FIX_SONAME'])
        self.assertFalse(report['hal_abi_verified'])

    def test_absolute_android_symlink_not_host_path(self):
        (self.root / 'vendor/lib64/link.so').symlink_to('/odm/lib64/libreal.so')
        item = audit(self.root, 'vendor/lib64/link.so')['entries'][0]
        self.assertEqual(item['resolved_source'], 'odm/lib64/libreal.so')
        self.assertEqual(item['status'], 'present')

    def test_relative_android_symlink(self):
        (self.root / 'vendor/lib64/link.so').symlink_to('../../odm/lib64/libreal.so')
        self.assertEqual(audit(self.root, 'vendor/lib64/link.so')['counts'], {'present': 1})

    def test_external_link_is_not_present_or_missing(self):
        (self.root / 'vendor/lib64/link.so').symlink_to('/system/lib64/libc.so')
        self.assertEqual(audit(self.root, 'vendor/lib64/link.so')['counts'], {'external_symlink_unverified': 1})

    def test_missing_and_unselected_partition_separate(self):
        self.assertEqual(audit(self.root, 'vendor/lib64/missing.so\nsystem/lib64/libc.so')['counts'],
                         {'missing': 1, 'outside_scope': 1})

    def test_generated_symlink_not_an_input(self):
        report = audit(self.root, 'odm/lib64/libreal.so;SYMLINK=vendor/lib64/link.so')
        self.assertEqual(report['counts'], {'present': 1})
        self.assertEqual(report['entries'][0]['symlinks'], ['vendor/lib64/link.so'])

    def test_explicit_extra_partition_scope(self):
        (self.root/'system_ext/lib64').mkdir(parents=True)
        (self.root/'system_ext/lib64/libtest.so').write_bytes(b'extension')
        text = 'system_ext/lib64/libtest.so\nproduct/etc/unselected.xml'
        self.assertEqual(audit(self.root,text)['counts'], {'outside_scope':2})
        result = audit(self.root,text,{'vendor','odm','system_ext'})
        self.assertEqual(result['counts'], {'present':1,'outside_scope':1})
        self.assertEqual(result['scope'], ['odm','system_ext','vendor'])

    def test_selected_partition_required_and_safe(self):
        for scope in (set(), {'../vendor'}, {'system_ext'}):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                audit(self.root,'vendor/a',scope)
        (self.root/'system_ext').symlink_to(self.root/'vendor',target_is_directory=True)
        with self.assertRaises(ValueError):audit(self.root,'vendor/a',{'system_ext'})

    def test_selected_cross_partition_link_and_missing(self):
        (self.root/'system_ext').mkdir()
        (self.root/'system_ext/a').write_bytes(b'a')
        (self.root/'vendor/a').symlink_to('/system_ext/a')
        result = audit(self.root,'vendor/a\nsystem_ext/b',{'vendor','odm','system_ext'})
        self.assertEqual(result['counts'], {'present':1,'missing':1})
        self.assertEqual(result['status'], 'incomplete_selected_partition_inputs')

    def test_duplicate_generated_owner_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate destination'):
            parse_list('odm/lib64/libreal.so;SYMLINK=vendor/lib64/link.so\nvendor/lib64/link.so')

    def test_identical_duplicates_removed_comments_preserved(self):
        before = '# first\nodm/lib64/libreal.so\n\n# second\nodm/lib64/libreal.so\n'
        after, removed = deduplicate_entries(before)
        self.assertEqual(after, '# first\nodm/lib64/libreal.so\n\n# second\n')
        self.assertEqual(removed, [{'line': 5, 'first_line': 2, 'entry': 'odm/lib64/libreal.so'}])

    def test_different_flags_or_sources_never_deduplicated(self):
        for text in ('vendor/a\nvendor/a;MAKE_COPY_RULE_ONLY', 'vendor/a:vendor/c\nvendor/b:vendor/c'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'duplicate destination'):
                deduplicate_entries(text)

    def test_source_pin_never_substituted_by_fixup_pin(self):
        sha1 = hashlib.sha1(b'blob').hexdigest()
        report = audit(self.root, 'odm/lib64/libreal.so|' + '0'*40 + '|' + sha1)
        self.assertEqual(report['counts'], {'source_pin_mismatch': 1})
        self.assertEqual(audit(self.root, 'odm/lib64/libreal.so|' + sha1)['counts'], {'present': 1})

    def test_unsafe_path_and_bad_pin_rejected(self):
        for line in ('../vendor/file', '/vendor/file', 'vendor/../file', 'vendor//file', 'vendor/file|bad'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_list(line)

    def test_loop_and_escape_rejected(self):
        link = self.root / 'vendor/lib64/link.so'
        for target in ('link.so', '../../../outside'):
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                audit(self.root, 'vendor/lib64/link.so')
            link.unlink()


if __name__ == '__main__':
    unittest.main()
