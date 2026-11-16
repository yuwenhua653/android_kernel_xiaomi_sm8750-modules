// SPDX-License-Identifier: GPL-2.0-only
/* Publish the Xiaomi userspace ABI only after a source sound card binds. */
#include <linux/device.h>
#include <linux/kobject.h>
#include <linux/of.h>
#include <linux/slab.h>
#include <linux/sysfs.h>
#include <sound/soc.h>
#include "msm-audio-defs.h"
#include "sun-annibale.h"

struct annibale_smartpa {
	struct kobject kobj;
	const char *family;
};

static ssize_t smartpa_type_show(struct kobject *kobj,
				struct kobj_attribute *attr, char *buf)
{
	struct annibale_smartpa *pa = container_of(kobj, struct annibale_smartpa, kobj);

	return sysfs_emit(buf, "%s\n", pa->family);
}

static struct kobj_attribute smartpa_type_attr = __ATTR_RO(smartpa_type);
static struct attribute *annibale_smartpa_attrs[] = {
	&smartpa_type_attr.attr,
	NULL,
};
ATTRIBUTE_GROUPS(annibale_smartpa);

static void annibale_smartpa_release(struct kobject *kobj)
{
	kfree(container_of(kobj, struct annibale_smartpa, kobj));
}

static const struct kobj_type annibale_smartpa_type = {
	.release = annibale_smartpa_release,
	.sysfs_ops = &kobj_sysfs_ops,
	.default_groups = annibale_smartpa_groups,
};

static void annibale_unpublish_smartpa(void *data)
{
	kobject_put(data);
}

int annibale_publish_smartpa(struct snd_soc_card *card)
{
	struct snd_soc_dai_link *link = NULL;
	struct annibale_smartpa *pa;
	const char *compatible, *family;
	int i, ret;

	if (!of_find_property(card->dev->of_node, "xiaomi,smartpa-codecs", NULL))
		return 0;
	for (i = 0; i < card->num_links; i++) {
		if (strcmp(card->dai_link[i].name, LPASS_BE_SEC_TDM_RX_0))
			continue;
		if (link)
			return -EINVAL;
		link = &card->dai_link[i];
	}
	if (!link || link->num_codecs != 2 || !link->codecs ||
	    !link->codecs[0].of_node || !link->codecs[1].of_node ||
	    link->codecs[0].of_node == link->codecs[1].of_node)
		return -EINVAL;
	if (of_device_is_compatible(link->codecs[0].of_node, "tfa,tfa98xx")) {
		compatible = "tfa,tfa98xx";
		family = "tfa98xx";
	} else {
		compatible = "si,sia91xx-i2c";
		family = "sia91xx";
	}
	for (i = 0; i < 2; i++) {
		if (!of_device_is_compatible(link->codecs[i].of_node, compatible) ||
		    !of_device_is_available(link->codecs[i].of_node) ||
		    !of_property_read_bool(link->codecs[i].of_node, "xiaomi,annibale-audio") ||
		    !link->codecs[i].dai_name)
			return -EINVAL;
	}
	pa = kzalloc(sizeof(*pa), GFP_KERNEL);
	if (!pa)
		return -ENOMEM;
	pa->family = family;
	/* A pre-existing owner is an error, never replaced or shared. */
	ret = kobject_init_and_add(&pa->kobj, &annibale_smartpa_type,
				  kernel_kobj, "smartpa");
	if (ret) {
		kobject_put(&pa->kobj);
		return ret;
	}
	return devm_add_action_or_reset(card->dev, annibale_unpublish_smartpa,
				      &pa->kobj);
}
