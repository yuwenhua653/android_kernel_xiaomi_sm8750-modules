# SPDX-License-Identifier: GPL-2.0-only
import os
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_annibale_erofs import inspect


@unittest.skipUnless(os.environ.get('ANNIBALE_STOCK_EROFS'), 'requires original OS4 EROFS fixture')
class StockMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data=Path(os.environ['ANNIBALE_STOCK_EROFS']).read_bytes()
        cls.data=data[:struct.unpack_from('<I',data,1060)[0]*4096]
        cls.root=struct.unpack_from('<I',data,1064)[0]*4096+struct.unpack_from('<H',data,1038)[0]*32

    def test_real_shared_labels(self):
        report=inspect(self.data,None,shared_xattrs=True)
        self.assertEqual(len(report),399)
        self.assertEqual(report['/etc']['selinux'],'u:object_r:vendor_configs_file:s0')
        self.assertEqual(report['/lib/modules']['selinux'],'u:object_r:vendor_file:s0')

    def test_default_profile_still_rejects_shared(self):
        with self.assertRaisesRegex(ValueError,'shared'):
            inspect(self.data,None)

    def test_shared_id_out_of_bounds_rejected(self):
        data=bytearray(self.data); fmt=struct.unpack_from('<H',data,self.root)[0]
        xat=self.root+(64 if fmt&1 else 32)
        self.assertGreater(data[xat+4],0)
        struct.pack_into('<I',data,xat+12,0xffffffff)
        with self.assertRaises(ValueError): inspect(data,None,shared_xattrs=True)

    def test_label_mode_and_feature_guards(self):
        with self.assertRaisesRegex(ValueError,'SELinux'):
            inspect(self.data,'u:object_r:wrong:s0',shared_xattrs=True)
        data=bytearray(self.data);struct.pack_into('<H',data,self.root+4,0o40777)
        with self.assertRaisesRegex(ValueError,'mode'):inspect(data,None,shared_xattrs=True)
        data=bytearray(self.data);struct.pack_into('<I',data,1104,0x80000001)
        with self.assertRaisesRegex(ValueError,'features'):inspect(data,None,shared_xattrs=True)


if __name__ == '__main__':unittest.main()
