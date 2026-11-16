/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef __SUN_ANNIBALE_H
#define __SUN_ANNIBALE_H
struct snd_soc_card;
struct device;
int annibale_bind_smartpa(struct snd_soc_card *card);
int annibale_prepare_dmic(struct device *dev);
int annibale_publish_smartpa(struct snd_soc_card *card);
#endif
