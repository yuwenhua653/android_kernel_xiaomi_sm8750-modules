# SPDX-License-Identifier: GPL-2.0-only
import unittest

from audit_annibale_elf_closure import check
from prepare_annibale_qesd_managers import convert, repair_policy
from prepare_annibale_qesdsys_source import sha


class QesdManagerTest(unittest.TestCase):
    def setUp(self):
        self.files = {n: b'input' for n in ['vendor/bin/qesdk-manager', 'vendor/bin/qesdk-secmanager',
            'vendor/etc/init/qesdk-manager.rc', 'vendor/etc/init/qesdk-secmanager.rc',
            'vendor/etc/seccomp_policy/qesdk.policy', 'vendor/etc/seccomp_policy/qesdksec.policy',
            'vendor/etc/vintf/manifest/qesdk-manager.xml']}
        self.text = '# QESD system service\nsystem_ext/priv-app/Service/Service.apk\n\n# QESD\n' + '\n'.join(self.files) + '\nvendor/lib64/libqesdk_manager.so\n'
        self.profile = {'input_sha256': {'proprietary-files.txt': sha(self.text.encode())}}
        self.policy = b'socket: arg0 == AF_UNIX\nmmap: arg2 in ~PROT_EXEC || arg2 in ~PROT_WRITE\nmprotect: arg2 in ~PROT_EXEC || arg2 in ~PROT_WRITE\nread: 1\n'

    def test_batch_retains_apk_and_stock_libraries(self):
        result = convert(self.text, self.files, self.profile)
        self.assertIn('# QESD manager supplement\n', result)
        self.assertIn('# QESD\nvendor/lib64/libqesdk_manager.so\n', result)
        self.assertEqual(result.count('|'), 7)
        for name in self.files:
            self.assertEqual(result.count(name + '|'), 1)
        self.assertIn('system_ext/priv-app/Service/Service.apk', result)

    def test_list_drift_and_repeat_rejected(self):
        for text in [self.text + '# changed\n', convert(self.text, self.files, self.profile)]:
            with self.assertRaisesRegex(ValueError, 'list drift'):
                convert(text, self.files, self.profile)

    def test_duplicate_destination_rejected(self):
        self.text += 'vendor/bin/other:vendor/bin/qesdk-manager\n'
        self.profile['input_sha256']['proprietary-files.txt'] = sha(self.text.encode())
        with self.assertRaisesRegex(ValueError, 'duplicate (owner|destination)'):
            convert(self.text, self.files, self.profile)

    def test_unreviewed_flags_rejected(self):
        self.text = self.text.replace('vendor/bin/qesdk-manager\n', 'vendor/bin/qesdk-manager;DISABLE_CHECKELF\n')
        self.profile['input_sha256']['proprietary-files.txt'] = sha(self.text.encode())
        with self.assertRaises(ValueError):
            convert(self.text, self.files, self.profile)

    def test_policy_additions_keep_restrictions(self):
        result = repair_policy(self.policy, ['sendto', 'exit'])
        self.assertTrue(result.startswith(self.policy))
        self.assertIn(b'sendto: 1\nexit: 1\n', result)
        with self.assertRaisesRegex(ValueError, 'already present'):
            repair_policy(result, ['sendto'])

    def test_broad_socket_or_wx_changes_rejected(self):
        for old, new in [(b'socket: arg0 == AF_UNIX', b'socket: 1'),
                         (b'mprotect: arg2 in ~PROT_EXEC || arg2 in ~PROT_WRITE', b'mprotect: 1')]:
            with self.assertRaisesRegex(ValueError, 'restriction drift'):
                repair_policy(self.policy.replace(old, new), ['sendto'])

    def test_duplicate_syscall_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate syscall'):
            repair_policy(self.policy + b'read: 1\n', ['sendto'])


class ElfClosureTest(unittest.TestCase):
    def objects(self):
        return {'exe': {'needed': ['vendor:lib'], 'imports': [('api', 'V2', False)], 'exports': set()},
                'vendor:lib': {'needed': [], 'imports': [], 'exports': {('api', 'V2')}}}

    def test_exact_version_resolves(self):
        self.assertEqual(check('exe', self.objects())['missing_strong'], [])

    def test_wrong_version_does_not_resolve(self):
        objects = self.objects()
        objects['vendor:lib']['exports'] = {('api', 'V1'), ('api', None)}
        self.assertEqual(len(check('exe', objects)['missing_strong']), 1)

    def test_unrelated_namespace_cannot_satisfy_import(self):
        objects = self.objects()
        objects['vendor:lib']['exports'] = set()
        objects['system:lib'] = {'needed': [], 'imports': [], 'exports': {('api', 'V2')}}
        self.assertEqual(len(check('exe', objects)['missing_strong']), 1)

    def test_other_branch_cannot_hide_missing_library_dependency(self):
        objects = self.objects()
        objects['exe']['needed'].append('system:other')
        objects['system:other'] = {'needed': [], 'imports': [], 'exports': {('private_api', None)}}
        objects['vendor:lib']['imports'] = [('private_api', None, False)]
        self.assertEqual(len(check('exe', objects)['missing_strong']), 1)

    def test_weak_missing_is_reported_without_strong_failure(self):
        objects = self.objects()
        objects['exe']['imports'].append(('optional', None, True))
        result = check('exe', objects)
        self.assertEqual(result['missing_strong'], [])
        self.assertEqual(len(result['unresolved_weak']), 1)

    def test_missing_needed_provider_fails(self):
        objects = self.objects()
        objects['vendor:lib']['needed'] = ['absent']
        with self.assertRaisesRegex(ValueError, 'missing DT_NEEDED'):
            check('exe', objects)


if __name__ == '__main__':
    unittest.main()
