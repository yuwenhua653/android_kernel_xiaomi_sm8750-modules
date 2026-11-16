// SPDX-License-Identifier: GPL-2.0-only
/* Explicit Annibale secondary-TDM binding; no global first-probe registry. */
#include <linux/device.h>
#include <linux/of.h>
#include <linux/slab.h>
#include <sound/soc.h>
#include "msm-audio-defs.h"
#include "sun-annibale.h"

static void annibale_put_codec_node(void *data)
{
	of_node_put(data);
}

int annibale_bind_smartpa(struct snd_soc_card *card)
{
	struct device *dev = card->dev;
	struct snd_soc_dai_link_component *codecs;
	struct snd_soc_dai_link *rx = NULL, *tx = NULL;
	struct of_phandle_args args;
	const char *dai_name;
	bool tfa = false;
	u32 tdm;
	int i, count, ret;

	if (!of_find_property(dev->of_node, "xiaomi,smartpa-codecs", NULL))
		return 0;

	count = of_count_phandle_with_args(dev->of_node, "xiaomi,smartpa-codecs",
					 "#sound-dai-cells");
	if (count != 2 || of_property_read_u32(dev->of_node,
					     "qcom,tdm-audio-intf", &tdm) || !tdm)
		return dev_err_probe(dev, -EINVAL, "Annibale requires two codecs and TDM\n");

	/* Validate both backend links before changing either of them. */
	for (i = 0; i < card->num_links; i++) {
		if (!strcmp(card->dai_link[i].name, LPASS_BE_SEC_TDM_RX_0)) {
			if (rx)
				return -EINVAL;
			rx = &card->dai_link[i];
		}
		if (!strcmp(card->dai_link[i].name, LPASS_BE_SEC_TDM_TX_0)) {
			if (tx)
				return -EINVAL;
			tx = &card->dai_link[i];
		}
	}
	if (!rx || !tx)
		return dev_err_probe(dev, -EINVAL, "secondary TDM backends missing\n");

	codecs = devm_kcalloc(dev, count, sizeof(*codecs), GFP_KERNEL);
	if (!codecs)
		return -ENOMEM;
	for (i = 0; i < count; i++) {
		ret = of_parse_phandle_with_args(dev->of_node, "xiaomi,smartpa-codecs",
						"#sound-dai-cells", i, &args);
		if (ret)
			return ret;
		ret = devm_add_action_or_reset(dev, annibale_put_codec_node, args.np);
		if (ret)
			return ret;
		if (args.args_count || !of_device_is_available(args.np) ||
		    !of_property_read_bool(args.np, "xiaomi,annibale-audio") ||
		    (!of_device_is_compatible(args.np, "tfa,tfa98xx") &&
		     !of_device_is_compatible(args.np, "si,sia91xx-i2c")))
			return -EINVAL;
		if (i == 0)
			tfa = of_device_is_compatible(args.np, "tfa,tfa98xx");
		else if (args.np == codecs[0].of_node ||
			 tfa != of_device_is_compatible(args.np, "tfa,tfa98xx"))
			return dev_err_probe(dev, -EINVAL, "duplicate or mixed smartpa codecs\n");

		/* Registered ASoC providers supply their real, possibly suffixed DAI names. */
		ret = snd_soc_get_dai_name(&args, &dai_name);
		if (ret)
			return dev_err_probe(dev, ret, "waiting for smartpa DAI %d\n", i);
		codecs[i].dai_name = devm_kstrdup(dev, dai_name, GFP_KERNEL);
		if (!codecs[i].dai_name)
			return -ENOMEM;
		codecs[i].of_node = args.np;
	}
	rx->codecs = codecs;
	rx->num_codecs = count;
	tx->codecs = codecs;
	tx->num_codecs = count;
	return 0;
}
