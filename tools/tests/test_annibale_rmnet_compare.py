# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compare_annibale_rmnet import compare


class RmnetComparisonTests(unittest.TestCase):
    def test_equal_metadata_does_not_require_equal_binaries(self):
        stock = {'parameters':['knob:bool','count:uint'],'depends':['rmnet_core'],'sha256':'stock'}
        native = dict(stock,parameters=['count:uint','knob:bool'],sha256='native')
        result = compare(stock,native)
        self.assertTrue(result['parameter_types_equal'])
        self.assertTrue(result['dependencies_equal'])

    def test_parameter_type_and_dependency_changes_detected(self):
        result = compare({'parameters':['knob:bool'],'depends':['rmnet_core']},
                         {'parameters':['knob:uint'],'depends':[]})
        self.assertFalse(result['parameter_types_equal'])
        self.assertFalse(result['dependencies_equal'])
        self.assertEqual(result['stock_only_parameters'],['knob:bool'])
        self.assertEqual(result['native_only_parameters'],['knob:uint'])
