// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <arpa/inet.h>
#include <linux/ip.h>
#include <linux/tcp.h>
#include <linux/udp.h>
typedef uint8_t u8;typedef uint16_t u16;
#define IP_MF 0x2000
#define IP_OFFSET 0x1fff
struct sk_buff { unsigned int len,readable;int offset;unsigned char data[256]; };
static int skb_network_offset(const struct sk_buff *s) { return s->offset; }
static void *skb_header_pointer(const struct sk_buff *s,int off,int len,void *buf)
{
    if(off<0 || (unsigned)off>s->readable || (unsigned)len>s->readable-off)return NULL;
    /* Copy models the non-linear fallback, without assuming a transport offset. */
    memcpy(buf,s->data+off,len);return buf;
}
#include "sla_under_test.inc"
static struct sk_buff tcp_packet(unsigned int ihl,unsigned int payload)
{
    struct sk_buff s={.offset=4,.len=4+ihl*4+20+payload};s.readable=s.len;
    struct iphdr ip={.ihl=ihl,.version=4,.protocol=IPPROTO_TCP,.tot_len=htons(s.len-4)};
    struct tcphdr tcp={.doff=5,.source=htons(123),.dest=htons(443)};
    memcpy(s.data+4,&ip,sizeof(ip));memcpy(s.data+4+ihl*4,&tcp,sizeof(tcp));return s;
}
int main(void)
{
    struct sla_packet p;
    struct sk_buff s=tcp_packet(5,8);
    assert(sla_parse_packet(&s,&p)&&p.payload_len==8&&ntohs(p.dest)==443);
    s=tcp_packet(6,12);assert(sla_parse_packet(&s,&p)&&p.payload_len==12);
    s=tcp_packet(5,0);((struct tcphdr *)(s.data+24))->fin=1;
    assert(sla_parse_packet(&s,&p)&&!p.payload_len&&p.closing);
    for(unsigned int n=0;n<44;n++) {
        s=tcp_packet(5,8);s.readable=n;assert(!sla_parse_packet(&s,&p));
    }
    s=tcp_packet(5,8);s.offset=-1;assert(!sla_parse_packet(&s,&p));
    s=tcp_packet(5,8);s.offset=100;assert(!sla_parse_packet(&s,&p));
    s=tcp_packet(5,8);((struct iphdr *)(s.data+4))->ihl=4;assert(!sla_parse_packet(&s,&p));
    s=tcp_packet(5,8);((struct iphdr *)(s.data+4))->version=6;assert(!sla_parse_packet(&s,&p));
    s=tcp_packet(5,8);((struct iphdr *)(s.data+4))->tot_len=htons(19);assert(!sla_parse_packet(&s,&p));
    s=tcp_packet(5,8);((struct iphdr *)(s.data+4))->tot_len=htons(255);assert(!sla_parse_packet(&s,&p));
    s=tcp_packet(5,8);((struct iphdr *)(s.data+4))->frag_off=htons(IP_MF);assert(!sla_parse_packet(&s,&p));
    ((struct iphdr *)(s.data+4))->frag_off=htons(1);assert(!sla_parse_packet(&s,&p));
    s=tcp_packet(5,8);((struct tcphdr *)(s.data+24))->doff=4;assert(!sla_parse_packet(&s,&p));
    s=tcp_packet(5,8);((struct tcphdr *)(s.data+24))->doff=15;assert(!sla_parse_packet(&s,&p));
    s=tcp_packet(5,8);((struct iphdr *)(s.data+4))->protocol=IPPROTO_ICMP;assert(!sla_parse_packet(&s,&p));
    s=tcp_packet(5,8);struct iphdr *ip=(void *)(s.data+4);struct udphdr *udp=(void *)(s.data+24);
    ip->protocol=IPPROTO_UDP;udp->len=htons(8);udp->dest=htons(53);
    assert(sla_parse_packet(&s,&p)&&p.protocol==IPPROTO_UDP&&ntohs(p.dest)==53);
    udp->len=htons(7);assert(!sla_parse_packet(&s,&p));
    udp->len=htons(100);assert(!sla_parse_packet(&s,&p));
    puts("PASS: SLA copied/non-linear header access, IPv4 options, short headers, malformed lengths, TCP flags, fragments and UDP bounds");
}
