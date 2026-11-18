# SPDX-License-Identifier: GPL-2.0-only
import tempfile
import unittest
from pathlib import Path

from prepare_annibale_os4_camera_qape import convert, sha, stream_matches


class CameraQapeMigrationTest(unittest.TestCase):
    def setUp(self):
        self.text = '# Camera\nvendor/lib64/old.so\n# Perf\nvendor/bin/current\n'
        self.profile = {'input_sha256': sha(self.text.encode()),
                        'retired_entries': ['vendor/lib64/old.so'],
                        'retained_sources': ['vendor/bin/current']}

    def test_retains_active_provider_and_comments(self):
        self.assertEqual(convert(self.text, self.profile), '# Camera\n# Perf\nvendor/bin/current\n')

    def test_repeated_application_rejected(self):
        with self.assertRaises(ValueError):
            convert(convert(self.text, self.profile), self.profile)

    def test_unreviewed_input_rejected(self):
        with self.assertRaises(ValueError):
            convert(self.text + 'vendor/bin/another\n', self.profile)

    def test_active_provider_retirement_rejected(self):
        self.profile['retired_entries'].append('vendor/bin/current')
        with self.assertRaises(ValueError):
            convert(self.text, self.profile)

    def test_missing_active_provider_rejected_even_with_new_hash(self):
        changed = self.text.replace('vendor/bin/current\n', '')
        self.profile['input_sha256'] = sha(changed.encode())
        with self.assertRaises(ValueError):
            convert(changed, self.profile)

    def test_duplicate_retirement_rejected(self):
        self.profile['retired_entries'] *= 2
        with self.assertRaises(ValueError):
            convert(self.text, self.profile)

    def test_flagged_legacy_entry_not_silently_removed(self):
        changed = self.text.replace('old.so', 'old.so;SYMLINK=vendor/lib64/alias.so')
        self.profile['input_sha256'] = sha(changed.encode())
        with self.assertRaises(ValueError):
            convert(changed, self.profile)

    def test_chunk_boundary_reference_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'consumer.so'
            path.write_bytes(b'\0' * (1024 * 1024 - 3) + b'libSEGModel.so\0')
            self.assertEqual(stream_matches(path, ['SEGModel', 'absent']), ['SEGModel'])

    def test_empty_consumer_has_no_references(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'consumer.so'
            path.write_bytes(b'')
            self.assertEqual(stream_matches(path, ['SEGModel']), [])


if __name__ == '__main__':
    unittest.main()
