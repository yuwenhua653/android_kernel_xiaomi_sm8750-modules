# SPDX-License-Identifier: GPL-2.0-only
"""Compile the actual readable and production-obfuscated init/exit functions."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


def function(source, name):
    match = re.search(r'static\s+(?:int|void)\s+__(?:init|exit)\s+' + name + r'\s*\(void\)\s*\{', source)
    if not match:
        raise ValueError('function missing: ' + name)
    start = source.index('{', match.start())
    depth = 1
    end = start + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


class RmnetLifecycleTests(unittest.TestCase):
    def exercise(self, obfuscated):
        root = Path(__file__).resolve().parents[2]/'qcom/opensource/datarmnet-ext'
        path = root/('perf' if obfuscated else 'src/perf')/'rmnet_perf_main.c'
        names = (['DATARMNET63abbdc3d3','DATARMNETa343229e33','DATARMNET7e9995246e',
                  'DATARMNETe80a33d544','DATARMNET31ff8cdc40','DATARMNET49c17a32bc',
                  'DATARMNET38bb6f2b7a','DATARMNET4b5170a1ef','DATARMNET8e1548cd2e','DATARMNET41e8cc085c']
                 if obfuscated else ['rmnet_perf_init','rmnet_perf_exit','rmnet_perf_tcp_init',
                  'rmnet_perf_udp_init','rmnet_perf_nl_register','rmnet_perf_set_hooks',
                  'rmnet_perf_tcp_exit','rmnet_perf_udp_exit','rmnet_perf_nl_unregister','rmnet_perf_unset_hooks'])
        aliases = ['under_init','under_exit','tcp_init','udp_init','nl_init','set_hooks',
                   'tcp_exit','udp_exit','nl_exit','unset_hooks']
        source = path.read_text()
        fixture = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#define __init
#define __exit
#define pr_info(...) ((void)0)
#define pr_err(...) ((void)0)
static int failure, tcp, udp, nl, hooks, tcp_clean, udp_clean;
static int tcp_init(void) { assert(!tcp); if(failure==1)return -11; tcp=1; return 0; }
static int udp_init(void) { assert(tcp&&!udp); if(failure==2)return -12; udp=1; return 0; }
static int nl_init(void) { assert(tcp&&udp&&!nl); if(failure==3)return -13; nl=1; return 0; }
static void set_hooks(void) { assert(tcp&&udp&&nl&&!hooks); hooks=1; }
static void unset_hooks(void) { assert(hooks); hooks=0; }
static void nl_exit(void) { assert(nl&&!hooks); nl=0; }
static void tcp_exit(void) { assert(tcp&&!hooks&&!nl&&!udp); tcp=0; tcp_clean++; }
static void udp_exit(void) { assert(udp&&!hooks&&!nl); udp=0; udp_clean++; }
'''
        fixture += '\n'.join('#define '+a+' '+b for a,b in zip(names,aliases))+'\n'
        fixture += function(source, names[0])+'\n'+function(source,names[1])
        fixture += r'''
int main(void) {
 for(failure=1;failure<=3;failure++) {
  tcp_clean=udp_clean=0;
  assert(under_init()==-10-failure);
  assert(!tcp&&!udp&&!nl&&!hooks);
  assert(tcp_clean==(failure>=2)&&udp_clean==(failure>=3));
 }
 failure=0;
 for(int i=0;i<100;i++) {
  tcp_clean=udp_clean=0;
  assert(under_init()==0);
  assert(tcp&&udp&&nl&&hooks&&!tcp_clean&&!udp_clean);
  under_exit();
  assert(!tcp&&!udp&&!nl&&!hooks&&tcp_clean==1&&udp_clean==1);
 }
 puts("PASS: actual RMNET init success, all init failures and 100 balanced init/exit cycles");
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'fixture.c').write_text(fixture)
            # Production source intentionally contains multiple obfuscated
            # statements per line; this suppresses only GCC's layout warning.
            subprocess.run(['cc','-std=gnu11','-Wall','-Werror','-Wno-misleading-indentation','-fsanitize=undefined',
                            '-fno-sanitize-recover=all',str(p/'fixture.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True,timeout=10)

    def test_production_obfuscated_lifecycle(self):
        self.exercise(True)

    def test_readable_lifecycle(self):
        self.exercise(False)


if __name__ == '__main__':
    unittest.main()
