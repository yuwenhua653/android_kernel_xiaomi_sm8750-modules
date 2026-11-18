// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/types.h>
#define __user
#define VOIP_STATE_MAX 21
#define GFP_KERNEL 0
#define scnprintf snprintf
static int stats_spin_lock,allocations;static bool fail_alloc,interrupted;
struct mutex { int held; };
static void mutex_init(struct mutex *m) { m->held=0; }
static int mutex_lock_interruptible(struct mutex *m)
{ if(interrupted)return -EINTR;assert(!m->held);m->held=1;return 0; }
static void mutex_unlock(struct mutex *m) { assert(m->held);m->held=0; }
#define spin_lock_irqsave(p,f) do { (f)=0;assert(!*(p));*(p)=1; } while(0)
#define spin_unlock_irqrestore(p,f) do { (void)(f);assert(*(p));*(p)=0; } while(0)
static void *kzalloc(size_t n,int flags)
{ (void)flags;if(fail_alloc)return NULL;allocations++;return calloc(1,n); }
static void kfree(void *p) { if(p){allocations--;free(p);} }
struct file { void *private_data; };struct inode { int unused; };
struct sla_voip_state { uint32_t address;uint16_t port; };
static struct sla_voip_state voip_state;
static ssize_t simple_read_from_buffer(char *dst,size_t n,loff_t *pos,const char *src,size_t len)
{
    assert(!stats_spin_lock);if(*pos<0)return -EINVAL;if((size_t)*pos>=len)return 0;
    if(n>len-*pos)n=len-*pos;
    memcpy(dst,src+*pos,n);*pos+=n;return n;
}
#include "sla_under_test.inc"
int main(void)
{
    struct inode inode={0};struct file file={0};char out[32]={0};loff_t pos=0;
    fail_alloc=true;assert(sla_voip_file_open(&inode,&file)==-ENOMEM);fail_alloc=false;
    assert(!sla_voip_file_open(&inode,&file));voip_state=(struct sla_voip_state){123,456};
    assert(!sla_voip_file_read(&file,out,0,&pos)&&voip_state.address==123);
    interrupted=true;assert(sla_voip_file_read(&file,out,1,&pos)==-EINTR&&voip_state.address==123);interrupted=false;
    assert(sla_voip_file_read(&file,out,2,&pos)==2&&!voip_state.address);
    voip_state=(struct sla_voip_state){999,888};
    assert(sla_voip_file_read(&file,out+2,30,&pos)==5);
    assert(!strcmp(out,"123,456")&&voip_state.address==999);
    assert(!sla_voip_file_read(&file,out,1,&pos));
    assert(!sla_voip_file_release(&inode,&file)&&!allocations);
    assert(!sla_voip_file_open(&inode,&file));pos=0;memset(out,0,sizeof(out));
    assert(sla_voip_file_read(&file,out,31,&pos)==7&&!strcmp(out,"999,888"));
    sla_voip_file_release(&inode,&file);assert(!allocations);
    puts("PASS: SLA VoIP alloc failure, interrupted/zero read, stable partial snapshot, EOF and next-open event");
}
