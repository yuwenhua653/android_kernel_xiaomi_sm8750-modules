# SPDX-License-Identifier: GPL-2.0-only
"""Execute actual control/cleanup code; mocks do not qualify live kernel races."""
from pathlib import Path
import re
import os
import shlex
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]/'qcom/opensource/datarmnet-ext'


def function(source,name):
    m=re.search(r'(?:static\s+)?(?:int|void)\s+(?:(?:__init|__exit)\s+)?'+name+r'\s*\(void\)\s*\{',source)
    if not m:raise ValueError(name)
    start=source.index('{',m.start());end=start+1;depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[m.start():end]


def run(code):
    with tempfile.TemporaryDirectory() as d:
        p=Path(d);(p/'test.c').write_text(code)
        subprocess.run(shlex.split(os.environ.get('CC', 'cc')) + ['-std=gnu11','-Wall','-Werror','-Wno-misleading-indentation',
                        '-fsanitize=undefined','-fno-sanitize-recover=all',str(p/'test.c'),'-o',str(p/'test')],check=True)
        subprocess.run([str(p/'test')],check=True,timeout=10)


class NetworkControls(unittest.TestCase):
    def mode(self,prefix):
        header=(ROOT/(prefix+'perf/rmnet_perf_mode.h')).read_text()
        header=re.sub(r'^#include <linux/[^>]+>\n','',header,flags=re.M)
        code=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define READ_ONCE(x) (*(volatile __typeof__(x) *)&(x))
#define WRITE_ONCE(x,v) ((x)=(v))
#define module_param_cb(...)
#define MODULE_PARM_DESC(...)
struct kernel_param { void *arg; };
struct kernel_param_ops {int (*set)(const char *,const struct kernel_param *);int (*get)(char *,const struct kernel_param *);};
static int sysfs_streq(const char *a,const char *b) {
 size_t n=strlen(b);return !strncmp(a,b,n)&&(!a[n]||(a[n]=='\n'&&!a[n+1]));
}
'''+header+r'''
int main(void) {
 struct kernel_param p={&rmnet_perf_mode};char buf[16];
 const char *names[]={"none","tcp","udp","all"};
 for(int cycle=0;cycle<100;cycle++)for(int i=0;i<4;i++) {
  assert(!rmnet_perf_mode_ops.set(names[i],&p));
  assert(rmnet_perf_mode_allows(RMNET_PERF_MODE_TCP)==!!(i&1));
  assert(rmnet_perf_mode_allows(RMNET_PERF_MODE_UDP)==!!(i&2));
  assert(rmnet_perf_mode_ops.get(buf,&p)==(int)strlen(names[i])+1);
  assert(!strncmp(buf,names[i],strlen(names[i])));
 }
 assert(!rmnet_perf_mode_ops.set("udp\n",&p));
 const char *bad[]={"UDP","udpx","","udp\nX","3","all tcp"};
 for(int i=0;i<6;i++){assert(rmnet_perf_mode_ops.set(bad[i],&p)==-EINVAL);assert(rmnet_perf_mode==2);}
 /* Independent quickack enable cannot bypass the administrative mode. */
 bool adaptive_tcp=true;assert(!(adaptive_tcp&&rmnet_perf_mode_allows(RMNET_PERF_MODE_TCP)));
 return 0;
}
'''
        run(code)
        src=(ROOT/(prefix+'perf/rmnet_perf_main.c')).read_text()
        self.assertEqual(src.count('rmnet_perf_mode_allows(RMNET_PERF_MODE_TCP)'),6)
        self.assertEqual(src.count('rmnet_perf_mode_allows(RMNET_PERF_MODE_UDP)'),4)

    def test_production_mode(self):self.mode('')
    def test_readable_mode(self):self.mode('src/')

    def shs(self,prefix):
        names=(['rmnet_shs_wq_genl_init','rmnet_shs_module_init','rmnet_shs_module_exit',
                'rmnet_shs_wq_genl_deinit','rmnet_shs_genl_family','rmnet_shs_userspace_connected','rmnet_shs_dev_notifier'] if prefix else
               ['DATARMNET0dbc627e8f','DATARMNET163e93649e','DATARMNETf3298dab6f',
                'DATARMNETeabd69d1ab','DATARMNETecc643c219','DATARMNETc252c204a8','DATARMNET5fc54f7a13'])
        aliases=['genl_init','under_init','under_exit','genl_deinit','family0','connected','notifier']
        code=r'''
#include <assert.h>
#include <stddef.h>
#define __init
#define __exit
#define pr_info(...)
#define pr_err(...)
#define rm_err(...)
#define trace_rmnet_shs_high(...)
static int failure,family0=0,rmnet_shs_genl_msg_family=1,connected,notifier,active[2],notified;
static int genl_register_family(int *f){assert(!active[*f]);if(failure==*f+1)return -10-failure;active[*f]=1;return 0;}
static int genl_unregister_family(int *f){assert(active[*f]);active[*f]=0;return 0;}
static int register_netdevice_notifier(int *n){assert(n==&notifier&&active[0]&&active[1]);if(failure==3)return -13;notified=1;return 0;}
static void unregister_netdevice_notifier(int *n){assert(n==&notifier&&notified);notified=0;}
static void genl_deinit(void){assert(!notified);genl_unregister_family(&rmnet_shs_genl_msg_family);genl_unregister_family(&family0);}
'''
        code+='\n'.join('#define '+n+' '+a for n,a in zip(names,aliases))+'\n'
        genl=(ROOT/(prefix+'shs/rmnet_shs_wq_genl.c')).read_text();config=(ROOT/(prefix+'shs/rmnet_shs_config.c')).read_text()
        code+=function(genl,names[0])+'\n'+function(config,names[1])+'\n'+function(config,names[2])
        code+=r'''
int main(void){for(failure=1;failure<=3;failure++){assert(under_init()==-10-failure);assert(!active[0]&&!active[1]&&!notified);}
 failure=0;for(int i=0;i<100;i++){assert(!under_init());assert(active[0]&&active[1]&&notified);under_exit();assert(!active[0]&&!active[1]&&!notified);}return 0;}
'''
        run(code)
        barrier=config.index('synchronize_rcu();')
        self.assertLess(config.index('tracepoint_synchronize_unregister();'),barrier)
        cleanup='rmnet_shs_cancel_table();' if prefix else 'DATARMNETeacad8334e();'
        self.assertLess(barrier,config.index(cleanup))

    def test_production_shs_failures(self):self.shs('')
    def test_readable_shs_failures(self):self.shs('src/')

    def offload(self,prefix):
        source=(ROOT/(prefix+'offload/rmnet_offload_state.c')).read_text()
        if prefix:
            names=['rmnet_offload_state_free','rmnet_offload','rmnet_offload_state_deregister_cb',
                   'rmnet_offload_unset_hooks','rmnet_offload_engine_disable_chain_flush','rmnet_offload_engine_flush_all_flows',
                   'rmnet_offload_deliver_descs','rmnet_offload_engine_exit',
                   'rmnet_offload_lock','rmnet_offload_unlock']
        else:
            header=(ROOT/'offload/rmnet_offload_main.h').read_text()
            deliver=re.findall(r'void\s+(DATARMNET\w+)\s*\(struct list_head\s*\*\s*\w*\s*\)',header)[0]
            names=['DATARMNET345f805b34','DATARMNETe05748b000','DATARMNETac9c8c14b1','DATARMNETba38823a2f',
                   'DATARMNET560e127137','DATARMNETae70636c90',deliver,'DATARMNETb98b78b8e3',
                   'DATARMNET664568fcd0','DATARMNET6a76048590']
        aliases=['under_free','state','deregister','unhook','unchain','flush','deliver','engine_exit','state_lock','state_unlock']
        code=r'''
#include <assert.h>
#include <stddef.h>
struct list_head {int count;};
#define LIST_HEAD(n) struct list_head n={0}
static int live,step,delivered,locked;static void *state;
static void deregister(void){assert(step++==0);}
static void unhook(void){assert(step++==1);}
static void unchain(void){assert(step++==2);}
static void synchronize_rcu(void){assert(step++==3&&!locked);}
static void state_lock(void){assert(step++==4&&!locked);locked=1;}
static void state_unlock(void){assert(step++==9&&locked&&!state&&!live);locked=0;}
static void flush(struct list_head *l){assert(step++==5&&state&&locked);l->count=17;}
static void deliver(struct list_head *l){assert(step++==6&&state&&locked&&l->count==17);delivered+=l->count;l->count=0;}
static void engine_exit(void){assert(step++==7&&locked&&delivered==17);}
static void kfree(void *p){assert(p==state&&locked&&step++==8);live=0;}
'''
        code+='\n'.join('#define '+n+' '+a for n,a in zip(names,aliases))+'\n'+function(source,names[0])
        code+='\nint main(void){for(int i=0;i<100;i++){step=delivered=0;live=1;state=&live;under_free();assert(!state&&!live&&!locked&&step==10);under_free();assert(step==10&&!locked);}return 0;}\n'
        run(code)

    def test_production_offload_drains(self):self.offload('')
    def test_readable_offload_drains(self):self.offload('src/')


if __name__=='__main__':unittest.main()
