/* SPDX-License-Identifier: GPL-2.0-only */
/* Exercise the actual DMIC lifecycle and published smartpa ABI with host mocks. */
#include <assert.h>
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#define EPROBE_DEFER 517
#define GFP_KERNEL 0
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct device_node { int family, available, marker, refs; };
struct device { struct device_node *of_node; };
struct snd_soc_dai_link_component { struct device_node *of_node; const char *dai_name; };
struct snd_soc_dai_link { const char *name; struct snd_soc_dai_link_component *codecs; int num_codecs; };
struct snd_soc_card { struct device *dev; struct snd_soc_dai_link *dai_link; int num_links; };
struct kobject;
struct attribute { const char *name; int mode; };
struct kobj_attribute { struct attribute attr; ssize_t (*show)(struct kobject *,struct kobj_attribute *,char *); };
struct attribute_group { struct attribute **attrs; };
struct sysfs_ops { int unused; };
struct kobj_type { void (*release)(struct kobject *); const struct sysfs_ops *sysfs_ops; const struct attribute_group **default_groups; };
struct kobject { const struct kobj_type *type; int added; };
static struct kobject kernel_object, *kernel_kobj=&kernel_object, *published;
static const struct sysfs_ops kobj_sysfs_ops;
#define __ATTR_RO(name) { {#name,0444}, name##_show }
#define ATTRIBUTE_GROUPS(name) \
 static const struct attribute_group name##_group={name##_attrs}; \
 static const struct attribute_group *name##_groups[]={&name##_group,NULL}
#define sysfs_emit snprintf_emit
static ssize_t snprintf_emit(char *buf,const char *format,const char *family) { return snprintf(buf,4096,format,family); }
static struct device_node providers[2], dmic;
static int property, missing_dmic, state, active_error, active_calls, sleep_calls;
static int fail_action, fail_alloc, allocated, released, existing_owner, add_error;
static struct { void (*fn)(void *); void *arg; } actions[4];
static int nactions;
static void *of_find_property(struct device_node *n,const char *s,void *p) { return property?n:NULL; }
static struct device_node *of_parse_phandle(struct device_node *n,const char *s,int index) {
 assert(!strcmp(s,"qcom,cdc-dmic-enable-gpios") && index==0);
 if(missing_dmic) return NULL;
 dmic.refs++; return &dmic;
}
static void of_node_put(struct device_node *n) { assert(n->refs>0); n->refs--; }
static int of_device_is_available(struct device_node *n) { return n->available; }
static int of_property_read_bool(struct device_node *n,const char *s) { return n->marker; }
static int of_device_is_compatible(struct device_node *n,const char *s) {
 return (n->family==1 && !strcmp(s,"tfa,tfa98xx")) || (n->family==2 && !strcmp(s,"si,sia91xx-i2c")) || (n->family==3 && !strcmp(s,"qcom,msm-cdc-pinctrl"));
}
static int dev_err_probe(struct device *d,int ret,const char *s,...) { return ret; }
static int devm_add_action_or_reset(struct device *d,void (*fn)(void *),void *p) {
 if(fail_action) { fn(p); return -ENOMEM; }
 actions[nactions].fn=fn; actions[nactions++].arg=p; return 0;
}
static int msm_cdc_pinctrl_get_state(struct device_node *n) { return state; }
static int msm_cdc_pinctrl_select_active_state(struct device_node *n) { active_calls++; return active_error; }
static int msm_cdc_pinctrl_select_sleep_state(struct device_node *n) { sleep_calls++; return 0; }
static void *kzalloc(size_t size,int flags) { if(fail_alloc)return NULL; allocated++; return calloc(1,size); }
static void kfree(void *p) { released++; free(p); }
static int kobject_init_and_add(struct kobject *k,const struct kobj_type *type,struct kobject *parent,const char *name) {
 k->type=type; assert(parent==kernel_kobj && !strcmp(name,"smartpa"));
 if(add_error)return add_error;
 if(existing_owner || published)return -EEXIST;
 k->added=1; published=k; return 0;
}
static void kobject_put(struct kobject *k) { if(k->added) { assert(published==k); published=NULL; } k->type->release(k); }
#include "sun-annibale-dmic.c"
#include "sun-annibale-sysfs.c"
static struct device dev;
static struct snd_soc_dai_link_component codecs[2];
static struct snd_soc_dai_link links[2];
static struct snd_soc_card card;
static void cleanup(void) {
 while(nactions) { --nactions; actions[nactions].fn(actions[nactions].arg); }
 assert(!dmic.refs && !published && allocated==released);
}
static void setup(void) {
 cleanup(); memset(providers,0,sizeof(providers)); memset(&dmic,0,sizeof(dmic));
 for(int i=0;i<2;i++) { providers[i].family=providers[i].available=providers[i].marker=1; codecs[i]=(struct snd_soc_dai_link_component){&providers[i],"real-provider-dai"}; }
 dmic.family=3;dmic.available=1;property=1;state=0;
 missing_dmic=active_error=active_calls=sleep_calls=fail_action=fail_alloc=existing_owner=add_error=0;
 dev.of_node=&providers[0]; links[0]=(struct snd_soc_dai_link){LPASS_BE_SEC_TDM_RX_0,codecs,2};links[1]=(struct snd_soc_dai_link){"other",NULL,0};
 card=(struct snd_soc_card){&dev,links,2};
}
static void expect_family(const char *family) {
 char buf[4096];assert(annibale_publish_smartpa(&card)==0 && published);
 assert(!strcmp(smartpa_type_attr.attr.name,"smartpa_type") && smartpa_type_attr.attr.mode==0444);
 assert(smartpa_type_attr.show(published,&smartpa_type_attr,buf)==(ssize_t)strlen(family));
 assert(!strcmp(buf,family));cleanup();
}
int main(void) {
 setup();property=0;assert(!annibale_prepare_dmic(&dev) && !annibale_publish_smartpa(&card));assert(!active_calls && !published);
 setup();missing_dmic=1;assert(annibale_prepare_dmic(&dev)==-EINVAL);cleanup();
 setup();dmic.available=0;assert(annibale_prepare_dmic(&dev)==-EINVAL);cleanup();
 setup();dmic.family=0;assert(annibale_prepare_dmic(&dev)==-EINVAL);cleanup();
 setup();state=-EINVAL;assert(annibale_prepare_dmic(&dev)==-EPROBE_DEFER && !active_calls);cleanup();
 state=0;assert(!annibale_prepare_dmic(&dev));assert(active_calls==1 && dmic.refs==1);cleanup();assert(sleep_calls==1);
 setup();active_error=-EIO;assert(annibale_prepare_dmic(&dev)==-EIO);cleanup();assert(sleep_calls==1);
 setup();fail_action=1;assert(annibale_prepare_dmic(&dev)==-ENOMEM);cleanup();assert(sleep_calls==1);
 setup();expect_family("tfa98xx\n");
 setup();providers[0].family=providers[1].family=2;expect_family("sia91xx\n");
 setup();providers[1].family=2;assert(annibale_publish_smartpa(&card)==-EINVAL);cleanup();
 setup();codecs[1].of_node=codecs[0].of_node;assert(annibale_publish_smartpa(&card)==-EINVAL);cleanup();
 setup();providers[1].marker=0;assert(annibale_publish_smartpa(&card)==-EINVAL);cleanup();
 setup();codecs[1].dai_name=NULL;assert(annibale_publish_smartpa(&card)==-EINVAL);cleanup();
 setup();links[1].name=links[0].name;assert(annibale_publish_smartpa(&card)==-EINVAL);cleanup();
 setup();existing_owner=1;assert(annibale_publish_smartpa(&card)==-EEXIST && existing_owner);cleanup();
 setup();add_error=-EIO;assert(annibale_publish_smartpa(&card)==-EIO);cleanup();
 setup();fail_alloc=1;assert(annibale_publish_smartpa(&card)==-ENOMEM);cleanup();
 setup();fail_action=1;assert(annibale_publish_smartpa(&card)==-ENOMEM);cleanup();
 /* Probe failure after DMIC activation must release both resources. */
 setup();assert(!annibale_prepare_dmic(&dev));assert(!annibale_publish_smartpa(&card));cleanup();assert(sleep_calls==1);
 setup();assert(!annibale_prepare_dmic(&dev));existing_owner=1;assert(annibale_publish_smartpa(&card)==-EEXIST);cleanup();assert(sleep_calls==1);
 return 0;
}
