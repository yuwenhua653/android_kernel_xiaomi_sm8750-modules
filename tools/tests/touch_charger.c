// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#define CORE_INIT_STAGE2 2
#define ts_err(...) ((void)0)
#define ts_info(...) ((void)0)
struct goodix_ts_core;
struct hw_ops { int (*charger_on)(struct goodix_ts_core *,bool); };
struct goodix_ts_core { int init_stage,core_mutex,charger_status,suspended;struct hw_ops *hw_ops; };
static struct goodix_ts_core *goodix_core_data;
static int calls,result;static bool last;
static void mutex_lock(int *p) { assert(!*p);*p=1; }
static void mutex_unlock(int *p) { assert(*p);*p=0; }
static int atomic_read(int *p) { return *p; }
static int charger(struct goodix_ts_core *p,bool on)
{ assert(p==goodix_core_data&&p->core_mutex);calls++;last=on;return result; }
#include "power_under_test.inc"
int main(void)
{
    goodix_set_charge_state(1);assert(!calls);
    struct hw_ops hw={charger};struct goodix_ts_core core={.hw_ops=&hw,.init_stage=2};goodix_core_data=&core;
    goodix_set_charge_state(-1);assert(!calls);
    goodix_set_charge_state(3);assert(calls==1&&last&&core.charger_status==3&&!core.core_mutex);
    core.suspended=1;goodix_set_charge_state(0);assert(calls==1&&core.charger_status==0);
    core.suspended=0;mutex_lock(&core.core_mutex);goodix_reset_charge_state(&core,core.charger_status);mutex_unlock(&core.core_mutex);
    assert(calls==2&&!last);
    result=-5;goodix_set_charge_state(5);assert(calls==3&&last&&!core.core_mutex&&core.charger_status==5);
    core.init_stage=1;goodix_set_charge_state(0);assert(calls==3);
    core.init_stage=2;hw.charger_on=NULL;goodix_set_charge_state(0);assert(calls==3&&!core.core_mutex);
    puts("PASS: charger connect/unplug, suspend cache, resume off command, unknown state and error unlock");
}
