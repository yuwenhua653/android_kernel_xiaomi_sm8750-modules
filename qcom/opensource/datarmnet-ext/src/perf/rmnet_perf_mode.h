/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef RMNET_PERF_MODE_H
#define RMNET_PERF_MODE_H

#include <linux/moduleparam.h>
#include <linux/string.h>

/* Administrative mode is independent of the quickack controller's knobs.
 * Publish one mask so a packet cannot observe a half-written TCP/UDP pair.
 * Mode changes affect new decisions; existing work drains through its normal
 * lifetime. They do not unload the module or change core QMAP deaggregation.
 */
#define RMNET_PERF_MODE_TCP 1U
#define RMNET_PERF_MODE_UDP 2U
#define RMNET_PERF_MODE_ALL 3U
static unsigned int rmnet_perf_mode = RMNET_PERF_MODE_ALL;

static int rmnet_perf_mode_set(const char *value, const struct kernel_param *kp)
{
	unsigned int mode;

	if (sysfs_streq(value, "all"))
		mode = RMNET_PERF_MODE_ALL;
	else if (sysfs_streq(value, "tcp"))
		mode = RMNET_PERF_MODE_TCP;
	else if (sysfs_streq(value, "udp"))
		mode = RMNET_PERF_MODE_UDP;
	else if (sysfs_streq(value, "none"))
		mode = 0;
	else
		return -EINVAL;

	WRITE_ONCE(*(unsigned int *)kp->arg, mode);
	return 0;
}

static int rmnet_perf_mode_get(char *buffer, const struct kernel_param *kp)
{
	static const char * const names[] = { "none", "tcp", "udp", "all" };
	unsigned int mode = READ_ONCE(*(unsigned int *)kp->arg);

	return sprintf(buffer, "%s\n", names[mode]);
}

static const struct kernel_param_ops rmnet_perf_mode_ops = {
	.set = rmnet_perf_mode_set,
	.get = rmnet_perf_mode_get,
};
module_param_cb(rmnet_perf_opt_mode, &rmnet_perf_mode_ops, &rmnet_perf_mode, 0644);
MODULE_PARM_DESC(rmnet_perf_opt_mode, "Protocol optimization: all, tcp, udp or none");

static inline bool rmnet_perf_mode_allows(unsigned int protocol)
{
	return READ_ONCE(rmnet_perf_mode) & protocol;
}
#endif
