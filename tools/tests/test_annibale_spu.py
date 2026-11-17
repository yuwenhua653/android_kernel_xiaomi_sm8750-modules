# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_plan_annibale_modules import module
from test_annibale_power import cells, pack
from plan_annibale_modules import resolve
from annibale_spu import PROFILE, ROOTS, SUPPLIERS
from build_annibale_modules import PLATFORM_GROUPS, build_options
from check_annibale_spu_dt import inspect


class SpuPlanTests(unittest.TestCase):
    def setUp(self):
        names = ROOTS | set.union(*SUPPLIERS.values())
        self.v = {'release':'test','modules':{n:module(n) for n in names}}
        self.p = {'schema_version':1,'profile':'native-source-qualification','boot_mode':'normal','complete_device':False,'spu_profile':PROFILE,'roots':sorted(ROOTS),'board_requires':{n:{'modules':sorted(s),'reason':'fixture'} for n,s in SUPPLIERS.items()},'ownership':[{'name':n,'partition':'vendor_dlkm','source':'source-build','reason':'fixture'} for n in names]}

    def test_firmware_selection_before_ipc(self):
        plan=resolve(self.v,self.p,set())['partitions']['vendor_dlkm']
        self.assertLess(plan.index('qcom_spss'),plan.index('spss_utils'))
        self.assertLess(plan.index('spss_utils'),plan.index('spcom'))

    def test_missing_glink(self):
        self.p['roots'].remove('qcom_glink_spss')
        with self.assertRaisesRegex(ValueError,'SPU driver: qcom_glink_spss'):
            resolve(self.v,self.p,set())

    def test_independent_utils_root_does_not_guarantee_order(self):
        self.p['board_requires']['spcom']['modules'].remove('spss_utils')
        with self.assertRaisesRegex(ValueError,'SPU suppliers: spcom'):
            resolve(self.v,self.p,set())

    def test_spu_in_unified_build(self):
        self.assertIn('qcom/opensource/spu-kernel',PLATFORM_GROUPS)
        self.assertIn('SPU_ROOT=/stage/qcom/opensource/spu-kernel',build_options(Path('/kernel'),Path('/stage'),'audio'))


    def test_missing_kernel_provider_stops_before_compilation(self):
        tool = Path(__file__).resolve().parents[1] / 'build_annibale_modules.py'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = ('kernel/Makefile', 'out/include/generated/autoconf.h',
                     'out/include/config/kernel.release', 'clang/clang')
            for name in paths:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture')
            for missing in ('QCOM_SPSS', 'RPMSG_QCOM_GLINK_SPSS'):
                options = ['ARCH_SUN=y', 'MODULES=y', 'QCOM_PANEL_EVENT_NOTIFIER=m',
                           'QCOM_SPSS=m', 'RPMSG_QCOM_GLINK_SPSS=m']
                (root/'out/.config').write_text('\n'.join('CONFIG_'+o for o in options if not o.startswith(missing+'=')))
                run = subprocess.run([sys.executable, '-B', str(tool), '--kernel', str(root/'kernel'),
                    '--kernel-out', str(root/'out'), '--clang-bin', str(root/'clang'),
                    '--output', str(root/'stage'), '--profile', 'platform', '--objects'],
                    text=True, capture_output=True)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn('required SPU provider configuration missing: CONFIG_'+missing+'=m', run.stderr)
                self.assertFalse((root/'stage').exists())


class SpuDtTests(unittest.TestCase):
    def setUp(self):
        self.nodes={'/':{},'/soc':{},'/reserved-memory':{'#address-cells':pack(2),'#size-cells':pack(2)},
         '/reserved-memory/sp':{'phandle':pack(1),'reg':pack(0,0x9b0a0000,0,0x1e0000),'no-map':b''},
         '/soc/r':{'phandle':pack(2),'compatible':b'qcom,sun-spss-pas\0','memory-region':pack(1),'qcom,extra-size':pack(0x1000),'qcom,spss-scsr-bits':pack(24,25),'cx-supply':pack(3),'sensors-supply':pack(3),'qcom,qmp':pack(3),'clocks':pack(3,0),'interconnects':pack(3,41,3,513)},
         '/soc/provider':{'phandle':pack(3),'#clock-cells':pack(1),'#interconnect-cells':pack(1),'#mbox-cells':pack(2)},
         '/soc/r/glink-edge':{'qcom,remote-pid':pack(8),'mboxes':pack(3,8,0),'interrupt-parent':pack(3)},
         '/soc/utils':{'compatible':b'qcom,spss-utils\0','qcom,rproc-handle':pack(2),'pil-mem':pack(1),'qcom,pil-size':pack(0xf0000),'qcom,spss-dev-firmware-name':b'spss1d.mdt\0','qcom,spss-test-firmware-name':b'spss1t.mdt\0','qcom,spss-prod-firmware-name':b'spss1p.mdt\0'},
         '/soc/comm':{'compatible':b'qcom,spcom\0','qcom,rproc-handle':pack(2),'qcom,boot-enabled':b'','qcom,spcom-ch-names':b'sp_kernel\0sp_ssr\0'}}

    def run_dt(self):
        return inspect(SimpleNamespace(nodes=self.nodes),cells)

    def test_complete_static_chain(self):
        self.assertEqual(self.run_dt()['memory']['size'],0x1e0000)

    def test_different_remoteproc(self):
        self.nodes['/soc/comm']['qcom,rproc-handle']=pack(3)
        with self.assertRaisesRegex(ValueError,'different remoteproc'):self.run_dt()

    def test_memory_overflow(self):
        self.nodes['/soc/utils']['qcom,pil-size']=pack(0x1e0000)
        with self.assertRaisesRegex(ValueError,'exceeds reserved memory'):self.run_dt()

    def test_disabled_provider_ancestor(self):
        self.nodes['/soc/provider']['status']=b'disabled\0'
        with self.assertRaisesRegex(ValueError,'disabled supplier'):self.run_dt()

    def test_no_map_required(self):
        del self.nodes['/reserved-memory/sp']['no-map']
        with self.assertRaisesRegex(ValueError,'reserved no-map'):self.run_dt()


class SpuReferenceTests(unittest.TestCase):
    def test_actual_probe_prefix_balances_remoteproc_reference(self):
        # Compile the actual probe prefix up to the first chardev allocation.
        # Later chardev setup is outside this narrowly scoped failure-path test.
        repo=Path(__file__).resolve().parents[2]
        source=(repo/'qcom/opensource/spu-kernel/drivers/spss_utils.c').read_text()
        start=source.index('static int spss_probe(struct platform_device *pdev)\n{')
        end=source.index('\tspss_utils_dev = kzalloc',start)
        prefix=source[start:end]+'\treturn 0;\n}\n'
        stubs=r'''
#include <assert.h>
#include <errno.h>
#include <stddef.h>
#define EPROBE_DEFER 517
#define SPSS_FW_TYPE_DEV 0
#define SPSS_FW_TYPE_TEST 1
#define SPSS_FW_TYPE_PROD 2
#define SPSS_FW_TYPE_NONE 3
#define pr_err(...) ((void)0)
struct device_node { int dummy; };
struct device { struct device_node *of_node; };
struct platform_device { struct device dev; };
struct property { unsigned int *value; };
struct rproc { int dummy; };
static struct device *spss_dev;
static int firmware_type, set_result, puts, gets, available, parse_result;
static const char *firmware_name, *dev_firmware_name="d", *test_firmware_name="t", *prod_firmware_name="p", *none_firmware_name="n";
static struct rproc remote;
static unsigned int phandle=1;
static struct property prop={&phandle};
static void platform_set_drvdata(struct platform_device *p,void *d) {(void)p;(void)d;}
static int spss_parse_dt(struct device_node *n) {(void)n;return parse_result;}
static struct property *of_find_property(struct device_node *n,const char *k,void *v) {(void)n;(void)k;(void)v;return &prop;}
static unsigned int be32_to_cpup(unsigned int *p) {return *p;}
static struct rproc *rproc_get_by_phandle(unsigned int p) {(void)p;gets++;return available?&remote:NULL;}
static int qcom_spss_set_fw_name(struct rproc *p,const char *name) {assert(p==&remote);assert(name==dev_firmware_name);return set_result;}
static void rproc_put(struct rproc *p) {assert(p==&remote);puts++;}
'''
        main=r'''
int main(void) {
 struct device_node node={0}; struct platform_device dev={{&node}};
 available=1;set_result=-ENOMEM;assert(spss_probe(&dev)==-EPROBE_DEFER);assert(gets==1 && puts==1);
 gets=puts=0;set_result=0;assert(spss_probe(&dev)==0);assert(gets==1 && puts==1);
 gets=puts=0;available=0;assert(spss_probe(&dev)==-EPROBE_DEFER);assert(gets==1 && puts==0);
 gets=puts=0;parse_result=-EINVAL;assert(spss_probe(&dev)==-EINVAL);assert(gets==0 && puts==0);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);c=root/'probe.c';binary=root/'probe'
            c.write_text(stubs+prefix+main)
            subprocess.run(['cc','-std=c11','-Wall','-Werror','-Wno-unused-variable','-fsanitize=undefined',str(c),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
