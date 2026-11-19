/*
    Copyright (c) 2018, The Linux Foundation. All rights reserved.

    This program is free software; you can redistribute it and/or modify it under the terms
    of the GNU General Public License version 2 and only version 2 as published by the Free
    Software Foundation.

    This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
    without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
    See the GNU General Public License for more details.
*/
#include <linux/gfp.h>
#include <linux/kernel.h>
#include <linux/export.h>
#include <linux/module.h>
#include <asm/uaccess.h>
#include <linux/seq_file.h>
#include <linux/mm.h>
#include <linux/slab.h>
#include <linux/tcp.h>
#include <linux/udp.h>
#include <linux/ip.h>
#include <linux/version.h>
#include <linux/skbuff.h>
#include <linux/netfilter.h>
#include <linux/netfilter_ipv4.h>
#include <linux/moduleparam.h>
#include <linux/spinlock.h>
#include <linux/netfilter_ipv4/ip_tables.h>
#include <linux/hash.h>
#include <linux/proc_fs.h>
#include <linux/list.h>
#include <linux/ktime.h>
#include <linux/mutex.h>
#include <linux/vmalloc.h>
#include <net/sock.h>
#include <net/ip.h>

#include "sla_stats.h"

/* Annibale stock data sizes; layout checks do not prove behavioral parity. */
static_assert(sizeof(struct sla_config) == 268);
static_assert(sizeof(struct sla_voip_state) == 8);
static_assert(sizeof(struct sla_stats_entry) == 16);
static_assert(sizeof(struct sla_interface_stats) == 20480);

/* about fs config */
#define USE_PROCFS

/* about stats */
#define STATS_BUF_SIZE (sizeof(struct sla_interface_stats)) //16*(1+ENTRY_TOTAL) = (20*1024)

#define MMAP_FILE_SUFFIX "_mmap"
#define TOTAL_STATS_FILE_SUFFIX "_stats"
#define VOIP_STATS_FILE "sla_voip_state"

#if (LINUX_VERSION_CODE < KERNEL_VERSION(5, 17, 0))
/*
 * Commit 359745d78351 ("proc: remove PDE_DATA() completely")
 * Replaced PDE_DATA() with pde_data()
 */
#define pde_data(inode) PDE_DATA(inode)
#endif

static struct sla_config config_data;
static struct sla_voip_state voip_state;
static u64 pkt_alloc_num = 0;
static u64 pkt_free_num = 0;

/* Lock order: control_mutex -> stats_spin_lock. Proc removal holds neither
 * stats_spin_lock nor a callback's own lock. Packet callbacks never take the
 * control mutex. All config, interface and packet-table data use stats lock.
 */
static DEFINE_MUTEX(control_mutex);
static DEFINE_SPINLOCK(stats_spin_lock);

static void sla_iface_release(struct kref *ref)
{
    struct sla_interface *iface = container_of(ref, struct sla_interface, ref);

    vfree(iface->mmap_struct);
    kfree(iface);
}


LIST_HEAD(sla_iface_list) ;


/* about port hash list */
#define PORT_HASH_BITS 8
#define PORT_HASH_SIZE (1<<PORT_HASH_BITS)
#define MAX_SIZE_DEFAULT    (4*1024)
#define LIMIT_TIME_DEFAULT  (5)


struct uplink_pkt
{
    struct hlist_node   hlist;
    u16 local_port;
};

struct hlist_head   pkt_list[PORT_HASH_SIZE];


/* about fs */

static int total_stats_show(struct seq_file *seq, void *unused)
{
    struct sla_interface *iface = seq->private;
    unsigned long flags;
    u64 value;

    spin_lock_irqsave(&stats_spin_lock, flags);
    value = iface->total_trfc;
    spin_unlock_irqrestore(&stats_spin_lock, flags);
    seq_printf(seq, "%llu\n", value);
    return 0;
}

static int total_stats_open(struct inode *inode, struct file *file)
{
    struct sla_interface *iface = pde_data(inode);
    int ret;

    kref_get(&iface->ref);
    ret = single_open(file, total_stats_show, iface);
    if (ret)
        kref_put(&iface->ref, sla_iface_release);
    return ret;
}

static int total_stats_release(struct inode *inode, struct file *file)
{
    struct seq_file *seq = file->private_data;
    struct sla_interface *iface = seq->private;
    int ret = single_release(inode, file);

    kref_put(&iface->ref, sla_iface_release);
    return ret;
}

static ssize_t total_stats_write(struct file *file, const char __user *buf,
                                size_t count, loff_t *pos)
{
    struct seq_file *seq = file->private_data;
    struct sla_interface *iface = seq->private;
    unsigned long flags;
    u64 value;
    int ret = kstrtoull_from_user(buf, count, 0, &value);

    if (ret)
        return ret;
    spin_lock_irqsave(&stats_spin_lock, flags);
    iface->total_trfc = value;
    spin_unlock_irqrestore(&stats_spin_lock, flags);
    return count;
}

static const struct proc_ops fops_u64 = {
    .proc_open = total_stats_open,
    .proc_release = total_stats_release,
    .proc_read = seq_read,
    .proc_write = total_stats_write,
    .proc_lseek = seq_lseek,
};

/* dir */
static struct proc_dir_entry *sla_dir;
/* config file */
static struct proc_dir_entry *config_file; //Used for SLA config: enable, prots, reset_traffic and so on

static struct sla_interface * sla_find_interface(const char *interface_name);
/* sla voip file */
static struct proc_dir_entry *sla_voip_file;

/* Packet hash helpers require stats_spin_lock; there are no RCU readers. */

static inline struct hlist_head *pkt_hlist_head(u16 port)
{
    return &pkt_list[hash_32(port, PORT_HASH_BITS)];
}

static struct uplink_pkt *pkt_find(u16 port)
{
    struct uplink_pkt *pkt;

    lockdep_assert_held(&stats_spin_lock);
    hlist_for_each_entry(pkt, pkt_hlist_head(port), hlist)
    {
        if (pkt->local_port == port)
            return pkt;
    }

    return NULL;
}

static void pkt_add(u16 port)
{
    struct uplink_pkt *pkt;

    if(pkt_find(port))
        return;

    pkt = kzalloc(sizeof(*pkt), GFP_ATOMIC);
    if (!pkt)
        return;

    pkt->local_port = port;
    ++ pkt_alloc_num;
    hlist_add_head(&pkt->hlist, pkt_hlist_head(port));
}

static void pkt_release(struct uplink_pkt *pkt)
{
    lockdep_assert_held(&stats_spin_lock);
    ++ pkt_free_num;
    hlist_del(&pkt->hlist);
    kfree(pkt);
}


static void pkt_hlist_init(void)
{
    unsigned int h;

    for (h = 0; h < PORT_HASH_SIZE; h++)
        INIT_HLIST_HEAD(&pkt_list[h]);
}

static void pkt_hlist_deinit(void)
{
    struct uplink_pkt *pkt;
    struct hlist_node *next;
    unsigned int h;

    lockdep_assert_held(&stats_spin_lock);
    for (h = 0; h < PORT_HASH_SIZE; h++)
        hlist_for_each_entry_safe(pkt, next, &pkt_list[h], hlist)
            pkt_release(pkt);
}

static void pkt_hlist_print(void)
{
    struct uplink_pkt *pkt;
    unsigned int h;

    for (h = 0; h < PORT_HASH_SIZE; h++)
    {
        hlist_for_each_entry(pkt, &pkt_list[h], hlist)
            printk("%s() pkt_list[%d] local_port=%d\n", __func__, h, pkt->local_port);
    }
}

/* Read headers through skb_header_pointer: transport offsets need not be set
 * at PRE_ROUTING and the skb may be non-linear. Fragments are not classified.
 */
struct sla_packet {
    u8 protocol;
    __be16 source, dest;
    __be32 daddr;
    u16 payload_len;
    bool closing;
};

static bool sla_parse_packet(const struct sk_buff *skb, struct sla_packet *pkt)
{
    struct iphdr ipbuf;
    struct tcphdr tcpbuf;
    struct udphdr udpbuf;
    const struct iphdr *ip;
    const struct tcphdr *tcp;
    const struct udphdr *udp;
    unsigned int iplen, total, translen;
    int offset = skb_network_offset(skb);

    if (offset < 0 || offset > skb->len)
        return false;
    ip = skb_header_pointer(skb, offset, sizeof(ipbuf), &ipbuf);
    if (!ip || ip->version != 4 || ip->ihl < 5 ||
        (ntohs(ip->frag_off) & (IP_MF | IP_OFFSET)))
        return false;
    iplen = ip->ihl * 4;
    total = ntohs(ip->tot_len);
    if (total < iplen || total > skb->len - offset)
        return false;
    pkt->protocol = ip->protocol;
    pkt->daddr = ip->daddr;
    pkt->closing = false;
    if (pkt->protocol == IPPROTO_TCP) {
        if (total - iplen < sizeof(tcpbuf))
            return false;
        tcp = skb_header_pointer(skb, offset + iplen, sizeof(tcpbuf), &tcpbuf);
        if (!tcp || tcp->doff < 5)
            return false;
        translen = tcp->doff * 4;
        if (translen > total - iplen)
            return false;
        pkt->source = tcp->source;
        pkt->dest = tcp->dest;
        pkt->closing = tcp->fin || tcp->rst;
    } else if (pkt->protocol == IPPROTO_UDP) {
        if (total - iplen < sizeof(udpbuf))
            return false;
        udp = skb_header_pointer(skb, offset + iplen, sizeof(udpbuf), &udpbuf);
        if (!udp || ntohs(udp->len) < sizeof(udpbuf) ||
            ntohs(udp->len) > total - iplen)
            return false;
        translen = sizeof(udpbuf);
        pkt->source = udp->source;
        pkt->dest = udp->dest;
    } else {
        return false;
    }
    pkt->payload_len = total - iplen - translen;
    return true;
}

static bool sla_pkt_valid(const struct sla_packet *packet, u8 link_type)
{
    struct uplink_pkt *pkt;
    u16 port;

    lockdep_assert_held(&stats_spin_lock);
    if (packet->protocol != IPPROTO_TCP)
        return false;
    if (packet->payload_len)
        return true;
    port = ntohs(link_type == LT_UPLINK ? packet->source : packet->dest);
    if (packet->closing) {
        pkt = pkt_find(port);
        if (pkt)
            pkt_release(pkt);
    }
    return false;
}

static bool sla_pkt_consolidate(struct sla_interface_stats *stats, u32 index)
{
    u32 prev;
    struct sla_stats_entry* entry = &stats->entries[index];

    if (index == 0)
        prev = ENTRY_TOTAL - 1;
    else
        prev = index - 1;

    if(stats->entries[prev].discard)
        return false;

    if(stats->entries[prev].port != entry->port)
        return false;

    if((stats->entries[prev].timestamp + config_data.limit_time) < entry->timestamp)
        return false;

    if((stats->entries[prev].size + entry->size) > config_data.max_size)
        return false;

    stats->entries[prev].size += entry->size;

    return true;
}

static unsigned int sla_ipv4_in(void *priv, struct sk_buff *skb,
                                const struct nf_hook_state *state)
{
    struct sla_packet packet;
    struct sla_interface *iface;
    struct sla_interface_stats *p;
    struct sla_stats_entry *entry;
    struct uplink_pkt *pkt;
    struct timespec64 tm;
    bool consolidated = false;
    unsigned long flags;

    if (!state->in || !sla_parse_packet(skb, &packet))
        return NF_ACCEPT;
    spin_lock_irqsave(&stats_spin_lock, flags);
    if (!config_data.enable || !config_data.rate_on ||
        !sla_pkt_valid(&packet, LT_DOWNLINK))
        goto out;
    iface = sla_find_interface(state->in->name);
    if (!iface)
        goto out;
    p = iface->mmap_struct;
    iface->total_trfc += skb->len;
    ktime_get_real_ts64(&tm);
    entry = &p->entries[iface->write_idx];
    entry->link_type = LT_DOWNLINK;
    entry->timestamp = tm.tv_sec * 1000 + tm.tv_nsec / 1000000;
    entry->size = skb->len + 14;
    entry->port = ntohs(packet.dest);
    pkt = pkt_find(entry->port);
    if (pkt) {
        pkt_release(pkt);
        entry->discard = 1;
    } else {
        entry->discard = 0;
        consolidated = sla_pkt_consolidate(p, iface->write_idx);
    }
    if (!consolidated) {
        iface->write_idx = (iface->write_idx + 1) % ENTRY_TOTAL;
        WRITE_ONCE(p->cur_idx, iface->write_idx);
    } else {
        memset(entry, 0, sizeof(*entry));
    }
out:
    spin_unlock_irqrestore(&stats_spin_lock, flags);
    return NF_ACCEPT;
}

static unsigned int sla_ipv4_out(void *priv, struct sk_buff *skb,
                                 const struct nf_hook_state *state)
{
    struct sla_packet packet;
    struct sla_interface *iface;
    struct sla_interface_stats *p;
    struct sla_stats_entry *entry;
    struct timespec64 tm;
    unsigned long flags;

    if (!state->out || !sla_parse_packet(skb, &packet))
        return NF_ACCEPT;
    spin_lock_irqsave(&stats_spin_lock, flags);
    if (!config_data.enable)
        goto out;
    if (config_data.voip_enable && config_data.voip_uid &&
        packet.protocol == IPPROTO_UDP && skb->sk && sk_fullsock(skb->sk)) {
        if (config_data.voip_uid == __kuid_val(skb->sk->sk_uid) &&
            !voip_state.address && packet.dest != htons(53)) {
            voip_state.address = packet.daddr;
            voip_state.port = packet.dest;
        }
        goto out;
    }
    if (!config_data.rate_on || !sla_pkt_valid(&packet, LT_UPLINK))
        goto out;
    iface = sla_find_interface(state->out->name);
    if (!iface)
        goto out;
    p = iface->mmap_struct;
    ktime_get_real_ts64(&tm);
    pkt_add(ntohs(packet.source));
    entry = &p->entries[iface->write_idx];
    entry->link_type = LT_UPLINK;
    entry->timestamp = tm.tv_sec * 1000 + tm.tv_nsec / 1000000;
    entry->size = skb->len + 14;
    entry->port = ntohs(packet.source);
    entry->discard = 1;
    iface->write_idx = (iface->write_idx + 1) % ENTRY_TOTAL;
    WRITE_ONCE(p->cur_idx, iface->write_idx);
out:
    spin_unlock_irqrestore(&stats_spin_lock, flags);
    return NF_ACCEPT;
}

static struct nf_hook_ops sla_ipv4_ops[] __read_mostly =
{
    {
        .hook       = sla_ipv4_in,
        .pf         = NFPROTO_IPV4,
        .hooknum    = NF_INET_PRE_ROUTING,
        .priority   = NF_IP_PRI_CONNTRACK+2,
    },
    {
        .hook       = sla_ipv4_out,
        .pf         = NFPROTO_IPV4,
        .hooknum    = NF_INET_POST_ROUTING,
        .priority   = NF_IP_PRI_LAST,
    },
};

static ssize_t stats_read(struct file *file, char __user *user_buf,
                          size_t count, loff_t *ppos)
{
    struct sla_interface *iface = file->private_data;

    return simple_read_from_buffer(user_buf, count, ppos,
                                   iface->mmap_struct, STATS_BUF_SIZE);
}

static void stats_vma_open(struct vm_area_struct *vma)
{
    struct sla_interface *iface = vma->vm_private_data;

    /* The parent VMA already holds a module reference during fork/split. */
    __module_get(THIS_MODULE);
    kref_get(&iface->ref);
}

static void stats_vma_close(struct vm_area_struct *vma)
{
    struct sla_interface *iface = vma->vm_private_data;

    kref_put(&iface->ref, sla_iface_release);
    module_put(THIS_MODULE);
}

static const struct vm_operations_struct stats_vm_ops = {
    .open = stats_vma_open,
    .close = stats_vma_close,
};

static int stats_map(struct file *file, struct vm_area_struct *vma)
{
    struct sla_interface *iface = file->private_data;
    unsigned long size = vma->vm_end - vma->vm_start;
    int ret;

    if (!iface)
        return -ENODEV;
    /* mmap clears VM_SHARED for MAP_SHARED on an O_RDONLY descriptor.
     * VM_MAYSHARE retains the mapping type; do not promote it to writable.
     * Annibale slad uses precisely that read-only shared mapping.
     */
    if (vma->vm_pgoff || !size || size > STATS_BUF_SIZE ||
        !(vma->vm_flags & VM_MAYSHARE))
        return -EINVAL;
    if (vma->vm_flags & VM_EXEC)
        return -EPERM;
    if (!try_module_get(THIS_MODULE))
        return -ENODEV;
    vm_flags_clear(vma, VM_MAYEXEC);
    vm_flags_set(vma, VM_DONTEXPAND | VM_DONTDUMP);
    ret = remap_vmalloc_range(vma, iface->mmap_struct, 0);
    if (ret) {
        module_put(THIS_MODULE);
        return ret;
    }
    /* proc_remove can release the file before the VMA is closed. */
    kref_get(&iface->ref);
    vma->vm_private_data = iface;
    vma->vm_ops = &stats_vm_ops;
    return 0;
}

static int stats_open(struct inode *inode, struct file *file)
{
    struct sla_interface *iface = pde_data(inode);

    kref_get(&iface->ref);
    file->private_data = iface;
    return 0;
}

static int stats_release(struct inode *inode, struct file *file)
{
    struct sla_interface *iface = file->private_data;

    file->private_data = NULL;
    kref_put(&iface->ref, sla_iface_release);
    return 0;
}

static const struct proc_ops stats_fops = {
    .proc_open = stats_open,
    .proc_release = stats_release,
    .proc_read = stats_read,
    .proc_lseek = default_llseek,
    .proc_mmap = stats_map,
};

/* Per-open text snapshot makes partial reads stable and consumes state once. */
struct sla_voip_reader {
    struct mutex lock;
    bool captured;
    char text[VOIP_STATE_MAX];
    size_t length;
};

static int sla_voip_file_open(struct inode *inode, struct file *file)
{
    struct sla_voip_reader *reader = kzalloc(sizeof(*reader), GFP_KERNEL);

    if (!reader)
        return -ENOMEM;
    mutex_init(&reader->lock);
    file->private_data = reader;
    return 0;
}

static int sla_voip_file_release(struct inode *inode, struct file *file)
{
    kfree(file->private_data);
    file->private_data = NULL;
    return 0;
}

static ssize_t sla_voip_file_read(struct file *file, char __user *buffer,
                                size_t size, loff_t *pos)
{
    struct sla_voip_reader *reader = file->private_data;
    struct sla_voip_state snapshot;
    unsigned long flags;
    ssize_t ret;

    if (!size)
        return 0;
    ret = mutex_lock_interruptible(&reader->lock);
    if (ret)
        return ret;
    if (!reader->captured) {
        spin_lock_irqsave(&stats_spin_lock, flags);
        snapshot = voip_state;
        memset(&voip_state, 0, sizeof(voip_state));
        spin_unlock_irqrestore(&stats_spin_lock, flags);
        reader->length = scnprintf(reader->text, sizeof(reader->text),
                                   "%u,%d", snapshot.address, snapshot.port);
        reader->captured = true;
    }
    ret = simple_read_from_buffer(buffer, size, pos, reader->text, reader->length);
    mutex_unlock(&reader->lock);
    return ret;
}

static const struct proc_ops sla_voip_fops = {
    .proc_open = sla_voip_file_open,
    .proc_read = sla_voip_file_read,
    .proc_release = sla_voip_file_release,
};

static void sla_stats_data_init(struct sla_interface_stats *p)
{
    memset(p, 0, STATS_BUF_SIZE);

    p->magic_num = STATS_MAGIC;
    p->total = ENTRY_TOTAL;
    p->cur_idx = 0;
    p->reserve = 0;
}

/**
 *
 * @param interface_name
 *
 * @return struct sla_interface*
 *
 * This function itterates over sla_iface_list to find the
 * interface structure that matches interface_name.
 *
 * The caller needs to acquire stats_lock() before calling the
 * function and while using the returned sla_interface ptr.
 *
 * The caller also needs to release the lock by calling
 * stats_unlock() after using ( reading or writing to)
 * sla_interface ptr.
 */
static struct sla_interface * sla_find_interface(const char *interface_name)
{
    struct sla_interface * iface = NULL;

    lockdep_assert_held(&stats_spin_lock);
    list_for_each_entry (iface , &sla_iface_list, interface_list_hook)
    {
         if(strcmp(interface_name,iface->interface_name ) == 0)
         {
             return iface;
         }
    }

    return NULL;
}

static int sla_interface_start(const char *name)
{
    struct sla_interface *iface;
    unsigned long flags;
    char mmap_name[IF_NAME_LEN + sizeof(MMAP_FILE_SUFFIX)];
    char total_name[IF_NAME_LEN + sizeof(TOTAL_STATS_FILE_SUFFIX)];
    int ret = -ENOMEM;

    lockdep_assert_held(&control_mutex);
    if (!name || !*name || strlen(name) >= IF_NAME_LEN ||
        strchr(name, '/') || strchr(name, '\n'))
        return -EINVAL;
    spin_lock_irqsave(&stats_spin_lock, flags);
    iface = sla_find_interface(name);
    spin_unlock_irqrestore(&stats_spin_lock, flags);
    if (iface)
        return -EEXIST;
    iface = kzalloc(sizeof(*iface), GFP_KERNEL);
    if (!iface)
        return -ENOMEM;
    kref_init(&iface->ref); /* owner reference, retained through proc removal */
    strscpy(iface->interface_name, name, sizeof(iface->interface_name));
    iface->mmap_struct = vmalloc_user(PAGE_ALIGN(STATS_BUF_SIZE));
    if (!iface->mmap_struct)
        goto put_iface;
    sla_stats_data_init(iface->mmap_struct);
    snprintf(mmap_name, sizeof(mmap_name), "%s%s", name, MMAP_FILE_SUFFIX);
    snprintf(total_name, sizeof(total_name), "%s%s", name, TOTAL_STATS_FILE_SUFFIX);
    iface->mmap_file = proc_create_data(mmap_name, 0644, sla_dir,
                                         &stats_fops, iface);
    if (!iface->mmap_file)
        goto put_iface;
    iface->total_stats_file = proc_create_data(total_name, 0644, sla_dir,
                                                &fops_u64, iface);
    if (!iface->total_stats_file) {
        proc_remove(iface->mmap_file);
        goto put_iface;
    }
    spin_lock_irqsave(&stats_spin_lock, flags);
    list_add(&iface->interface_list_hook, &sla_iface_list);
    spin_unlock_irqrestore(&stats_spin_lock, flags);
    return 0;
put_iface:
    kref_put(&iface->ref, sla_iface_release);
    return ret;
}

static void sla_stats_disable(void)
{
    struct sla_interface *iface, *next;
    unsigned long flags;
    LIST_HEAD(retired);

    lockdep_assert_held(&control_mutex);
    spin_lock_irqsave(&stats_spin_lock, flags);
    config_data.enable = 0;
    config_data.rate_on = 0;
    /* Also drain interfaces created before enable=1. */
    list_splice_init(&sla_iface_list, &retired);
    pkt_hlist_deinit();
    spin_unlock_irqrestore(&stats_spin_lock, flags);

    list_for_each_entry_safe(iface, next, &retired, interface_list_hook) {
        list_del(&iface->interface_list_hook);
        proc_remove(iface->mmap_file);
        proc_remove(iface->total_stats_file);
        kref_put(&iface->ref, sla_iface_release);
    }
    /* Existing mappings retain their stopped buffer until their last close. */
}

static void sla_stats_enable(void)
{
    unsigned long flags;

    lockdep_assert_held(&control_mutex);
    spin_lock_irqsave(&stats_spin_lock, flags);
    if (!config_data.enable) {
        config_data.enable = 1;
        config_data.rate_on = 1;
    }
    spin_unlock_irqrestore(&stats_spin_lock, flags);
}

static int config_file_show(struct seq_file *s, void *data)
{
    struct sla_config snapshot;
    struct sla_config *config = &snapshot;
    unsigned long flags;
    int i;

    spin_lock_irqsave(&stats_spin_lock, flags);
    snapshot = config_data;
    spin_unlock_irqrestore(&stats_spin_lock, flags);

    seq_printf(s, CMD_ENABLE"%d\n", config->enable);
    seq_printf(s, CMD_RATE_ON"%d\n", config->rate_on);

    seq_puts(s, CMD_PORTS);
    if(0 != config->ports[0])
    {
        seq_printf(s, "%d", config->ports[0]);

        for(i=1; (i<PORTS_MAX) && (0!=config->ports[i]); i++)
            seq_printf(s, ",%d", config->ports[i]);
    }

    seq_printf(s, "\n");
    seq_printf(s, CMD_MAX_SIZE"%d\n", config->max_size);
    seq_printf(s, CMD_LIMIT_TIME"%d\n", config->limit_time);
    seq_printf(s, CMD_VOIP_ENABLE"%d\n", config->voip_enable);
    seq_printf(s, CMD_VOIP_UID"%u\n", config->voip_uid);

    return 0;
}

static int config_file_open(struct inode *inode, struct file *filp)
{
    return single_open(filp, config_file_show, pde_data(inode));
}

static int sla_stats_command(char *cmd)
{
    unsigned long num;
    int len, i;
    char *p, *buf;

    lockdep_assert_held(&stats_spin_lock);
    len = strlen(CMD_RATE_ON);
    if(0 == strncmp(cmd, CMD_RATE_ON, len))
    {
        printk("#### %s rate_on=%c\n", __func__, cmd[len]);
        if('1' == cmd[len] && 0 == cmd[len+1])
            config_data.rate_on = 1;
        else if('0' == cmd[len] && 0 == cmd[len+1])
            config_data.rate_on = 0;

        return 0;
    }

    len = strlen(CMD_PORTS);
    if(0 == strncmp(cmd, CMD_PORTS, len))
    {
        printk("#### %s ports=[%s]\n", __func__, cmd+len);
        buf = cmd+len;
        i = 0;
        while(NULL != (p = strsep(&buf, ",")))
        {
            num = simple_strtoul(p, NULL, 10);
            if((0 < num) && (num <= 0xFFFF))
            {
                config_data.ports[i] = num & 0xFFFF;
                printk("#### %s ports=[%d]\n", __func__, config_data.ports[i]);

                i++;
                if(i >= PORTS_MAX)
                    break;
            }
        }

        return 0;
    }

    len = strlen(CMD_RESET_TRAFFIC);
    if(0 == strncmp(cmd, CMD_RESET_TRAFFIC, len))
    {
        if('1' == cmd[len] && 0 == cmd[len+1])
        {
            struct sla_interface * iface = NULL;
            list_for_each_entry (iface , &sla_iface_list, interface_list_hook)
            {
                iface->total_trfc = 0;
            }
            printk("#### %s reset_traffic=%c\n", __func__, cmd[len]);

        }

        return 0;
    }

    len = strlen(CMD_HASH_PRINT);
    if(0 == strncmp(cmd, CMD_HASH_PRINT, len))
    {
        printk("#### %s hash print %llu, %llu\n", __func__, pkt_alloc_num, pkt_free_num);
        pkt_hlist_print();

        return 0;
    }

    len = strlen(CMD_HASH_CLEAR);
    if(0 == strncmp(cmd, CMD_HASH_CLEAR, len))
    {
        printk("#### %s hash clear\n", __func__);
        pkt_hlist_deinit();

        return 0;
    }

    len = strlen(CMD_MAX_SIZE);
    if(0 == strncmp(cmd, CMD_MAX_SIZE, len))
    {
        num = simple_strtoul(&cmd[len], NULL, 10);
        if(num < MAX_SIZE_DEFAULT || num > U16_MAX)
        {
            printk(KERN_ERR "#### %s max_size=%lu is invaild, need greater than %d\n", __func__, num, MAX_SIZE_DEFAULT);
        }
        else
        {
            config_data.max_size = num & 0xFFFF;
            printk("#### %s max_size=%d\n", __func__, config_data.max_size);
        }

        return 0;
    }

    len = strlen(CMD_LIMIT_TIME);
    if(0 == strncmp(cmd, CMD_LIMIT_TIME, len))
    {
        num = simple_strtoul(&cmd[len], NULL, 10);
        if(num < LIMIT_TIME_DEFAULT || num > U16_MAX)
        {
            printk(KERN_ERR "#### %s limit_time=%lu is invaild, need longer than %d\n", __func__, num, LIMIT_TIME_DEFAULT);
        }
        else
        {
            config_data.limit_time = num & 0xFFFF;
            printk("#### %s limit_time=%d\n", __func__, config_data.limit_time);
        }

        return 0;
    }

    len = strlen(CMD_VOIP_ENABLE);
    if(0 == strncmp(cmd, CMD_VOIP_ENABLE, len)) {
        printk("#### %s voip_enbale=%s\n", __func__, cmd+len);
        if('1' == cmd[len] && 0 == cmd[len+1]) {
            memset(&voip_state, 0, sizeof(voip_state));
            if (!sla_voip_file) {
                printk(KERN_ERR "#### %s Fail to open file: sla_voip_file\n", __func__);
                return -ENODEV;
            }
            config_data.voip_enable = 1;
        } else if('0' == cmd[len] && 0 == cmd[len+1]) {
            config_data.voip_enable = 0;
        }

        return 0;
    }

    len = strlen(CMD_VOIP_UID);
    if(0 == strncmp(cmd, CMD_VOIP_UID, len)) {
        printk("#### %s voip_uid=%s\n", __func__, cmd+len);
        config_data.voip_uid = simple_strtoul(cmd+len, NULL, 10);
        return 0;
    }

    return 0;
}


static ssize_t config_file_write(struct file *file, const char __user *buffer,
                                 size_t count, loff_t *ppos)
{
    char cmd[CONFIG_CMD_MAX + 1] = { 0 };
    unsigned long flags;
    int ret;

    if (!count)
        return 0;
    if (count > CONFIG_CMD_MAX)
        return -E2BIG;
    if (copy_from_user(cmd, buffer, count))
        return -EFAULT;
    if (cmd[count - 1] == '\n')
        cmd[count - 1] = '\0';
    ret = mutex_lock_interruptible(&control_mutex);
    if (ret)
        return ret;
    if (!strncmp(cmd, CMD_IFACE_ADD, strlen(CMD_IFACE_ADD))) {
        ret = sla_interface_start(cmd + strlen(CMD_IFACE_ADD));
    } else if (!strcmp(cmd, CMD_ENABLE "1")) {
        sla_stats_enable();
        ret = 0;
    } else if (!strcmp(cmd, CMD_ENABLE "0")) {
        sla_stats_disable();
        ret = 0;
    } else {
        spin_lock_irqsave(&stats_spin_lock, flags);
        ret = sla_stats_command(cmd);
        spin_unlock_irqrestore(&stats_spin_lock, flags);
    }
    mutex_unlock(&control_mutex);
    return ret < 0 ? ret : count;
}


#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0)
static const struct proc_ops config_fops =
{
    .proc_open = config_file_open,
    .proc_read = seq_read,
    .proc_write = config_file_write,
    .proc_lseek = seq_lseek,
    .proc_release = single_release,
};
#else
static const struct file_operations config_fops =
{
    .owner = THIS_MODULE,
    .open = config_file_open,
    .read = seq_read,
    .write = config_file_write,
    .llseek = seq_lseek,
    .release = single_release,
};
#endif

static int __init sla_static_collector_init(void)
{
    int err = 0;
    printk("#### %s in version V 3.0 \n", __func__);

    pkt_hlist_init();

    //creat config
    memset(&config_data, 0, sizeof(config_data));
    config_data.ports[0] = 80; //default
    config_data.ports[1] = 443;
    config_data.max_size = MAX_SIZE_DEFAULT;
    config_data.limit_time = LIMIT_TIME_DEFAULT;

    // init voip_state struct
    memset(&voip_state, 0, sizeof(voip_state));

    err = nf_register_net_hooks(&init_net, sla_ipv4_ops, ARRAY_SIZE(sla_ipv4_ops));
    if (err < 0)
        return err;

    sla_dir = proc_mkdir("sla", NULL);

    if (!sla_dir)
    {
        printk(KERN_ERR "#### %s Fail to create sla dir\n", __func__);
        err = -ENOMEM;
        goto unregister_hooks;
    }

    sla_voip_file = proc_create_data(VOIP_STATS_FILE, 0644, sla_dir, &sla_voip_fops, &voip_state);
    if (!sla_voip_file)
    {
        printk(KERN_ERR "#### %s Fail to create file: sla_voip_file\n", __func__);
        err = -ENOMEM;
        goto remove_proc;
    }

    /* Publish the writable control only after all other init can succeed. */
    config_file = proc_create_data("config", 0644, sla_dir, &config_fops, &config_data);
    if (!config_file)
    {
        err = -ENOMEM;
        goto remove_proc;
    }

    return 0;

remove_proc:
    proc_remove(sla_dir);
unregister_hooks:
    nf_unregister_net_hooks(&init_net, sla_ipv4_ops, ARRAY_SIZE(sla_ipv4_ops));
    return err;
}

static void __exit sla_static_collector_deinit(void)
{
    printk("#### sla_static_collector_deinit in\n");
    /* Drain control callbacks before acquiring their mutex during teardown. */
    proc_remove(config_file);
    nf_unregister_net_hooks(&init_net, sla_ipv4_ops, ARRAY_SIZE(sla_ipv4_ops));

    mutex_lock(&control_mutex);
    sla_stats_disable();
    mutex_unlock(&control_mutex);
    proc_remove(sla_dir);
}

MODULE_LICENSE("GPL v2");
module_init(sla_static_collector_init);
module_exit(sla_static_collector_deinit);
