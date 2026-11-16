// SPDX-License-Identifier: GPL-2.0-only
/* Annibale discrete DMIC enable pins, matching the published board policy. */
#include <linux/device.h>
#include <linux/of.h>
#include <asoc/msm-cdc-pinctrl.h>
#include "sun-annibale.h"

static void annibale_release_dmic(void *data)
{
	struct device_node *np = data;

	msm_cdc_pinctrl_select_sleep_state(np);
	of_node_put(np);
}

int annibale_prepare_dmic(struct device *dev)
{
	struct device_node *np;
	int ret;

	if (!of_find_property(dev->of_node, "xiaomi,smartpa-codecs", NULL))
		return 0;

	np = of_parse_phandle(dev->of_node, "qcom,cdc-dmic-enable-gpios", 0);
	if (!np)
		return dev_err_probe(dev, -EINVAL, "Annibale DMIC enable node missing\n");
	if (!of_device_is_available(np) ||
	    !of_device_is_compatible(np, "qcom,msm-cdc-pinctrl")) {
		ret = -EINVAL;
		goto put_node;
	}
	/* get_state returns -EINVAL when the pinctrl provider has not probed. */
	ret = msm_cdc_pinctrl_get_state(np);
	if (ret < 0) {
		ret = -EPROBE_DEFER;
		goto put_node;
	}
	ret = msm_cdc_pinctrl_select_active_state(np);
	if (ret) {
		/* A failed multi-pin selection may have partially changed the pins. */
		msm_cdc_pinctrl_select_sleep_state(np);
		goto put_node;
	}
	/* Keep enabled while the card is bound, as in Xiaomi's Annibale driver. */
	return devm_add_action_or_reset(dev, annibale_release_dmic, np);

put_node:
	of_node_put(np);
	return dev_err_probe(dev, ret, "Annibale DMIC enable unavailable\n");
}
