# SPDX-License-Identifier: GPL-2.0-only
"""Shared driver sources must not escape or disappear from the snapshot."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_annibale_modules import sha256, validate_stage


class SourceSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.stage = self.root / 'stage'
        (self.source / 'driver').mkdir(parents=True)
        (self.source / 'variant').mkdir()
        (self.source / 'driver/api.c').write_text('original source\n')
        (self.source / 'variant/driver').symlink_to('../driver/', target_is_directory=True)
        self.sources = {'driver/api.c': sha256(self.source / 'driver/api.c')}
        self.links = {'variant/driver': '../driver/'}

    def test_preserved_shared_source_and_tampering(self):
        shutil.copytree(self.source, self.stage, symlinks=True)
        validate_stage(self.stage, self.sources, self.links)
        (self.stage / 'variant/driver/api.c').write_text('changed through alias\n')
        with self.assertRaisesRegex(ValueError, 'staged source differs'):
            validate_stage(self.stage, self.sources, self.links)

    def test_dereferenced_directory_cannot_bypass_snapshot(self):
        shutil.copytree(self.source, self.stage, symlinks=False)
        with self.assertRaisesRegex(ValueError, 'staged symlink differs'):
            validate_stage(self.stage, self.sources, self.links)

    def test_changed_target_rejected_even_with_identical_bytes(self):
        shutil.copytree(self.source, self.stage, symlinks=True)
        shutil.copytree(self.stage / 'driver', self.stage / 'other')
        (self.stage / 'variant/driver').unlink()
        (self.stage / 'variant/driver').symlink_to('../other/')
        with self.assertRaisesRegex(ValueError, 'staged symlink differs'):
            validate_stage(self.stage, self.sources, self.links)

    def test_external_symlink_target_rejected(self):
        shutil.copytree(self.source, self.stage, symlinks=True)
        (self.stage / 'variant/driver').unlink()
        # Resolve to an existing directory outside stage, with the recorded target.
        target = '../../source/driver'
        (self.stage / 'variant/driver').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'escapes build'):
            validate_stage(self.stage, self.sources, {'variant/driver': target})


if __name__ == '__main__':
    unittest.main()
