import unittest

from check_annibale_vendor_runtime import check_service_owners


class ServiceOwnerTests(unittest.TestCase):
    def test_same_executable_is_still_duplicate_service(self):
        result = check_service_owners({'device.rc': 'service clock /vendor/bin/clock\n    user system\n',
                                       'vendor.rc': 'service clock /vendor/bin/clock\n    user system\n'})
        self.assertEqual(len(result['duplicates']['clock']), 2)

    def test_override_is_reported_for_review(self):
        result = check_service_owners({'a.rc': 'service clock /bin/a\n',
                                       'b.rc': 'service clock /bin/b\n    override\n'})
        self.assertTrue(result['duplicates']['clock'][1]['override'])

    def test_trigger_does_not_add_owner(self):
        result = check_service_owners({'a.rc': 'service clock /bin/a\n    disabled\non boot\n    start clock\n'})
        self.assertEqual(result['service_count'], 1)
        self.assertFalse(result['duplicates'])

    def test_duplicate_inside_one_file(self):
        result = check_service_owners({'a.rc': 'service clock /bin/a\nservice clock /bin/b\n'})
        self.assertEqual(len(result['duplicates']['clock']), 2)


if __name__ == '__main__':
    unittest.main()
