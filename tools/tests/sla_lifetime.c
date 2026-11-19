// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/types.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32;
typedef uint64_t u64; typedef uint32_t __be32; typedef uint16_t __be16;
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct kref { unsigned int count; };
static void kref_init(struct kref *r) { r->count=1; }
static void kref_get(struct kref *r) { assert(r->count);r->count++; }
static void kref_put(struct kref *r,void (*release)(struct kref *))
{ assert(r->count);if (!--r->count) release(r); }
struct list_head { struct list_head *next,*prev; };
#define LIST_HEAD(n) struct list_head n={&(n),&(n)}
static void list_add(struct list_head *n,struct list_head *h)
{ n->next=h->next;n->prev=h;h->next->prev=n;h->next=n; }
static void list_del(struct list_head *n)
{ n->next->prev=n->prev;n->prev->next=n->next; }
static bool list_empty(struct list_head *h) { return h->next==h; }
static void list_splice_init(struct list_head *h,struct list_head *to)
{
    if (!list_empty(h)) {
        to->next=h->next;to->prev=h->prev;to->next->prev=to;to->prev->next=to;
        h->next=h->prev=h;
    }
}
#define list_for_each_entry(v,h,m) \
    for (v=container_of((h)->next,__typeof__(*v),m);&v->m!=(h);v=container_of(v->m.next,__typeof__(*v),m))
#define list_for_each_entry_safe(v,n,h,m) \
    for(v=container_of((h)->next,__typeof__(*v),m),n=container_of(v->m.next,__typeof__(*v),m); \
        &v->m!=(h);v=n,n=container_of(n->m.next,__typeof__(*n),m))
#include "sla_stats.h"
#define STATS_BUF_SIZE sizeof(struct sla_interface_stats)
#define MMAP_FILE_SUFFIX "_mmap"
#define TOTAL_STATS_FILE_SUFFIX "_stats"
#define PAGE_ALIGN(x) (((x)+4095)&~4095UL)
#define GFP_KERNEL 0
#define __user
#define KERN_ERR ""
#define printk(...) ((void)0)
#define U16_MAX UINT16_MAX
#define MAX_SIZE_DEFAULT 4096
#define LIMIT_TIME_DEFAULT 5
#define simple_strtoul strtoul
static int stats_spin_lock,control_mutex=1;
static bool copy_fault,mutex_interrupted;
static int mutex_lock_interruptible(int *p)
{ if(mutex_interrupted)return -EINTR;assert(!*p);*p=1;return 0; }
static void mutex_unlock(int *p) { assert(*p);*p=0; }
static int copy_from_user(char *dst,const char *src,size_t n)
{ assert(!stats_spin_lock);if(copy_fault)return 1;memcpy(dst,src,n);return 0; }
#define lockdep_assert_held(p) assert(*(p)==1)
#define spin_lock_irqsave(p,f) do { (f)=0;assert(!*(p));*(p)=1; } while(0)
#define spin_unlock_irqrestore(p,f) do { (void)(f);assert(*(p)==1);*(p)=0; } while(0)
static int objects,buffers,fail_alloc,alloc_calls,proc_calls,fail_proc;
static void *kzalloc(size_t n,int flags)
{ (void)flags;if(++alloc_calls==fail_alloc)return NULL;objects++;return calloc(1,n); }
static void kfree(void *p) { if(p){assert(!stats_spin_lock);objects--;free(p);} }
static void *vmalloc_user(size_t n)
{ if(++alloc_calls==fail_alloc)return NULL;buffers++;return calloc(1,n); }
static void vfree(void *p) { if(p){assert(!stats_spin_lock);buffers--;free(p);} }
static ssize_t strscpy(char *d,const char *s,size_t n)
{ size_t len=strlen(s);if(len>=n)return -E2BIG;memcpy(d,s,len+1);return len; }
struct inode { void *data; };
struct file { void *private_data; };
#define pde_data(i) ((i)->data)
struct vm_area_struct;
struct vm_operations_struct {
    void (*open)(struct vm_area_struct *);
    void (*close)(struct vm_area_struct *);
};
struct vm_area_struct {
    unsigned long vm_start,vm_end,vm_pgoff,vm_flags;
    void *vm_private_data;
    const struct vm_operations_struct *vm_ops;
};
#define VM_SHARED 1
#define VM_EXEC 2
#define VM_MAYEXEC 4
#define VM_DONTEXPAND 8
#define VM_DONTDUMP 16
#define VM_MAYSHARE 32
#define VM_WRITE 64
#define VM_MAYWRITE 128
#define vm_flags_set(v,f) ((v)->vm_flags|=(f))
#define vm_flags_clear(v,f) ((v)->vm_flags&=~(f))
#define THIS_MODULE NULL
static int module_refs,map_error;static bool module_live=true;
static bool try_module_get(void *p) { (void)p;if(!module_live)return false;module_refs++;return true; }
static void __module_get(void *p) { (void)p;assert(module_refs);module_refs++; }
static void module_put(void *p) { (void)p;assert(module_refs>0);module_refs--; }
static int remap_vmalloc_range(struct vm_area_struct *v,void *p,unsigned long offset)
{ assert(p && !offset && v->vm_end>v->vm_start);return map_error; }
static int stats_open(struct inode *,struct file *);
static int stats_release(struct inode *,struct file *);
static int stats_map(struct file *,struct vm_area_struct *);
static void stats_vma_open(struct vm_area_struct *);
static void stats_vma_close(struct vm_area_struct *);
static const struct vm_operations_struct stats_vm_ops={stats_vma_open,stats_vma_close};
struct proc_ops { int dummy; };
static const struct proc_ops stats_fops={0},fops_u64={0};
struct proc_dir_entry { void *data; struct file *opened[4]; int count; };
static struct proc_dir_entry *sla_dir;
static struct proc_dir_entry *sla_voip_file;
static struct sla_config config_data;
static struct sla_voip_state voip_state;
static LIST_HEAD(sla_iface_list);
static struct file injected_file;
static struct vm_area_struct injected_map;
static bool inject_open_map;
static struct proc_dir_entry *proc_create_data(const char *name,int mode,
        struct proc_dir_entry *parent,const struct proc_ops *ops,void *data)
{
    (void)name;(void)mode;(void)parent;(void)ops;assert(!stats_spin_lock);
    if (++proc_calls==fail_proc)return NULL;
    struct proc_dir_entry *p=calloc(1,sizeof(*p));p->data=data;
    if(inject_open_map && proc_calls==1) {
        struct inode inode={data};stats_open(&inode,&injected_file);
        p->opened[p->count++]=&injected_file;
        injected_map=(struct vm_area_struct){.vm_start=4096,.vm_end=24576,.vm_flags=VM_SHARED|VM_MAYSHARE};
        assert(!stats_map(&injected_file,&injected_map));
    }
    return p;
}
static void proc_remove(struct proc_dir_entry *p)
{
    assert(!stats_spin_lock);
    if(!p)return;
    struct inode inode={p->data};
    for(int i=0;i<p->count;i++) stats_release(&inode,p->opened[i]);
    free(p);
}
static void pkt_hlist_print(void) { assert(stats_spin_lock); }
static int hash_clears;
static void pkt_hlist_deinit(void) { assert(stats_spin_lock);hash_clears++; }
#include "sla_under_test.inc"
static void reset_faults(void)
{ assert(!objects&&!buffers&&!module_refs&&list_empty(&sla_iface_list));
  fail_alloc=fail_proc=alloc_calls=proc_calls=0;inject_open_map=false; }
static struct sla_interface *first(void)
{ return container_of(sla_iface_list.next,struct sla_interface,interface_list_hook); }
static void open_file(struct sla_interface *iface,struct file *file)
{ struct inode inode={iface};assert(!stats_open(&inode,file));
  iface->mmap_file->opened[iface->mmap_file->count++]=file; }
int main(void)
{
    assert(sizeof(struct sla_config)==268 && STATS_BUF_SIZE==20480);
    for(int fail=1;fail<=2;fail++) {
        reset_faults();fail_alloc=fail;assert(sla_interface_start("wlan0")==-ENOMEM);
        assert(!objects&&!buffers);
    }
    for(int fail=1;fail<=2;fail++) {
        reset_faults();fail_proc=fail;assert(sla_interface_start("wlan0")==-ENOMEM);
        assert(!objects&&!buffers);
    }
    reset_faults();fail_proc=2;inject_open_map=true;
    assert(sla_interface_start("wlan0")==-ENOMEM);
    assert(objects==1&&buffers==1&&module_refs==1&&list_empty(&sla_iface_list));
    assert(injected_file.private_data==NULL);
    injected_map.vm_ops->close(&injected_map);reset_faults();
    assert(sla_interface_start("")==-EINVAL);
    assert(sla_interface_start("bad/name")==-EINVAL);
    assert(sla_interface_start("0123456789abcdef")==-EINVAL);
    assert(!sla_interface_start("wlan0"));
    assert(sla_interface_start("wlan0")==-EEXIST);
    struct sla_interface *old=first();struct file a={0},b={0};open_file(old,&a);open_file(old,&b);
    /* Linux 6.6 mmap clears VM_SHARED and VM_MAYWRITE for O_RDONLY, while
     * preserving VM_MAYSHARE. This matches slad's PROT_READ/MAP_SHARED call. */
    struct vm_area_struct v={.vm_start=4096,.vm_end=24576,.vm_flags=VM_MAYSHARE|VM_MAYEXEC};
    v.vm_pgoff=1;assert(stats_map(&a,&v)==-EINVAL);v.vm_pgoff=0;
    v.vm_end+=4096;assert(stats_map(&a,&v)==-EINVAL);v.vm_end-=4096;
    v.vm_flags|=VM_EXEC;assert(stats_map(&a,&v)==-EPERM);v.vm_flags&=~VM_EXEC;
    v.vm_flags&=~VM_MAYSHARE;assert(stats_map(&a,&v)==-EINVAL);v.vm_flags|=VM_MAYSHARE;
    module_live=false;assert(stats_map(&a,&v)==-ENODEV);module_live=true;
    map_error=-ENOMEM;assert(stats_map(&a,&v)==-ENOMEM&&!module_refs);map_error=0;
    assert(!stats_map(&a,&v));assert(!(v.vm_flags&VM_MAYEXEC));
    assert(!(v.vm_flags&(VM_SHARED|VM_WRITE|VM_MAYWRITE)));
    struct vm_area_struct child=v;child.vm_ops->open(&child);
    assert(old->ref.count==5&&module_refs==2);
    /* Disable before enable must still remove interfaces. Proc rundown drops
     * both file references; independent parent/child mapping references remain. */
    assert(!config_data.enable);sla_stats_disable();
    assert(a.private_data==NULL&&b.private_data==NULL&&old->ref.count==2);
    assert(objects==1&&buffers==1&&module_refs==2&&list_empty(&sla_iface_list));
    assert(!sla_interface_start("wlan0"));assert(first()!=old);
    sla_stats_enable();assert(config_data.enable&&config_data.rate_on);
    sla_stats_disable();assert(!config_data.enable&&objects==1);
    child.vm_ops->close(&child);assert(objects==1&&module_refs==1);
    v.vm_ops->close(&v);reset_faults();
    sla_stats_disable();assert(!objects&&hash_clears>=3);
    control_mutex=0;
    struct file config={0};loff_t pos=0;
    assert(config_file_write(&config,"",0,&pos)==0);
    assert(config_file_write(&config,"",CONFIG_CMD_MAX+1,&pos)==-E2BIG);
    copy_fault=true;assert(config_file_write(&config,"enable=1",8,&pos)==-EFAULT);copy_fault=false;
    mutex_interrupted=true;assert(config_file_write(&config,"enable=1",8,&pos)==-EINTR);mutex_interrupted=false;
    assert(config_file_write(&config,"iface=wlan0",11,&pos)==11);
    assert(config_file_write(&config,"iface=wlan0",11,&pos)==-EEXIST);
    assert(config_file_write(&config,"enable=1",8,&pos)==8&&config_data.enable);
    assert(config_file_write(&config,"rate_on=0\n",10,&pos)==10&&!config_data.rate_on);
    assert(config_file_write(&config,"hash_clear",10,&pos)==10);
    assert(config_file_write(&config,"enable=0\n",9,&pos)==9&&!config_data.enable);
    assert(!control_mutex&&!stats_spin_lock);reset_faults();
    puts("PASS: SLA alloc/proc failures, late publication failure with live mapping, mmap bounds/failure, fork, proc rundown, disabled cleanup and re-enable lifetime");
}
