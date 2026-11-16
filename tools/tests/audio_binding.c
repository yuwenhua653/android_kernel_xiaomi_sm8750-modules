/* SPDX-License-Identifier: GPL-2.0-only */
/* Host harness for the actual machine binding, with OF/ASoC probe failures. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#define EPROBE_DEFER 517
#define GFP_KERNEL 0
typedef uint32_t u32;
struct device_node { int family, available, marker, args, refs, dai_error; char dai[32]; };
struct device { struct device_node *of_node; };
struct of_phandle_args { struct device_node *np; int args_count; };
struct snd_soc_dai_link_component { struct device_node *of_node; const char *dai_name; };
struct snd_soc_dai_link { const char *name; struct snd_soc_dai_link_component *codecs; int num_codecs; };
struct snd_soc_card { struct device *dev; struct snd_soc_dai_link *dai_link; int num_links; };
static struct device_node nodes[2], *providers[2];
static void *allocs[8];
static struct { void (*fn)(void *); void *data; } actions[2];
static int nallocs, nactions, property, count, tdm, fail_alloc, allocations, fail_action, parse_error;
static void *of_find_property(struct device_node *n, const char *s, void *p) { return property ? n : NULL; }
static int of_count_phandle_with_args(struct device_node *n, const char *s, const char *a) { return count; }
static int of_property_read_u32(struct device_node *n, const char *s, u32 *v) { *v=tdm; return 0; }
static int dev_err_probe(struct device *d, int error, const char *s, ...) { return error; }
static void of_node_put(void *p) { struct device_node *n=p; assert(n->refs>0); n->refs--; }
static void *devm_kcalloc(struct device *d, size_t n, size_t size, int flags) {
 if (++allocations==fail_alloc) return NULL;
 void *p=calloc(n,size); assert(p); allocs[nallocs++]=p; return p;
}
static char *devm_kstrdup(struct device *d, const char *s, int flags) {
 char *p=devm_kcalloc(d,strlen(s)+1,1,flags); if(p) strcpy(p,s); return p;
}
static int of_parse_phandle_with_args(struct device_node *n, const char *s, const char *a, int i, struct of_phandle_args *v) {
 if (parse_error) return parse_error;
 v->np=providers[i]; v->args_count=v->np->args; v->np->refs++; return 0;
}
static int devm_add_action_or_reset(struct device *d, void (*fn)(void *), void *p) {
 if (fail_action) { fn(p); return -ENOMEM; }
 actions[nactions].fn=fn; actions[nactions++].data=p; return 0;
}
static int of_device_is_available(struct device_node *n) { return n->available; }
static int of_property_read_bool(struct device_node *n, const char *s) { return n->marker; }
static int of_device_is_compatible(struct device_node *n, const char *s) {
 return (n->family==1 && !strcmp(s,"tfa,tfa98xx")) || (n->family==2 && !strcmp(s,"si,sia91xx-i2c"));
}
static int snd_soc_get_dai_name(struct of_phandle_args *a, const char **name) { *name=a->np->dai; return a->np->dai_error; }
#include "sun-annibale.c"
static struct snd_soc_dai_link_component dummy;
static struct snd_soc_dai_link links[3];
static struct device dev;
static struct snd_soc_card card;
static void cleanup(void) {
 while(nactions) { --nactions; actions[nactions].fn(actions[nactions].data); }
 while(nallocs) free(allocs[--nallocs]);
 assert(!nodes[0].refs && !nodes[1].refs);
}
static void setup(void) {
 cleanup(); memset(nodes,0,sizeof(nodes));
 for(int i=0;i<2;i++) { providers[i]=&nodes[i]; nodes[i].family=1; nodes[i].available=nodes[i].marker=1; }
 strcpy(nodes[0].dai,"tfa98xx-aif-0-0036"); strcpy(nodes[1].dai,"tfa98xx-aif-0-0034");
 links[0]=(struct snd_soc_dai_link){LPASS_BE_SEC_TDM_RX_0,&dummy,1};
 links[1]=(struct snd_soc_dai_link){LPASS_BE_SEC_TDM_TX_0,&dummy,1};
 links[2]=(struct snd_soc_dai_link){"unrelated",&dummy,1};
 dev.of_node=&nodes[0]; card=(struct snd_soc_card){&dev,links,3};
 property=tdm=1; count=2; fail_alloc=allocations=fail_action=parse_error=0;
}
static void rejected(int expected) {
 assert(annibale_bind_smartpa(&card)==expected);
 for(int i=0;i<3;i++) { assert(links[i].codecs==&dummy); assert(links[i].num_codecs==1); }
 cleanup();
}
static void accepted(void) {
 assert(annibale_bind_smartpa(&card)==0);
 assert(links[0].num_codecs==2 && links[1].num_codecs==2);
 assert(links[0].codecs==links[1].codecs && links[2].codecs==&dummy);
 for(int i=0;i<2;i++) {
  assert(links[0].codecs[i].of_node==&nodes[i]);
  assert(!strcmp(links[0].codecs[i].dai_name,nodes[i].dai));
  assert(links[0].codecs[i].dai_name!=nodes[i].dai);
 }
 cleanup();
}
int main(void) {
 setup(); property=0; rejected(0);
 for(int n=0;n<4;n++) { if(n==2) continue; setup(); count=n; rejected(-EINVAL); }
 setup(); tdm=0; rejected(-EINVAL);
 setup(); links[1].name="missing"; rejected(-EINVAL);
 setup(); links[2].name=LPASS_BE_SEC_TDM_RX_0; rejected(-EINVAL);
 setup(); links[2].name=LPASS_BE_SEC_TDM_TX_0; rejected(-EINVAL);
 setup(); providers[1]=providers[0]; rejected(-EINVAL);
 setup(); nodes[1].family=2; rejected(-EINVAL);
 for(int i=0;i<2;i++) {
  setup(); nodes[i].available=0; rejected(-EINVAL);
  setup(); nodes[i].marker=0; rejected(-EINVAL);
  setup(); nodes[i].args=1; rejected(-EINVAL);
  setup(); nodes[i].family=3; rejected(-EINVAL);
  setup(); nodes[i].dai_error=-EPROBE_DEFER; rejected(-EPROBE_DEFER);
  nodes[i].dai_error=0; accepted(); /* retry, after failed-probe devres cleanup */
 }
 for(int i=1;i<=3;i++) { setup(); fail_alloc=i; rejected(-ENOMEM); }
 setup(); fail_action=1; rejected(-ENOMEM);
 setup(); parse_error=-ENOENT; rejected(-ENOENT);
 setup(); accepted();
 setup(); nodes[0].family=nodes[1].family=2; strcpy(nodes[0].dai,"sipa-dai"); strcpy(nodes[1].dai,"sipa-dai"); accepted();
 return 0;
}
