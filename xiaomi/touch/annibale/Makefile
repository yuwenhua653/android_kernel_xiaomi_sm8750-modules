# SPDX-License-Identifier: GPL-2.0-only
KERNEL_SRC ?= /lib/modules/$(shell uname -r)/build
KERNEL_OUT ?= $(KERNEL_SRC)

.PHONY: modules clean
modules clean:
	$(MAKE) -C $(KERNEL_SRC) O=$(KERNEL_OUT) M=$(CURDIR) \
		CONFIG_TOUCHSCREEN_XIAOMI_ANNIBALE=m $@
