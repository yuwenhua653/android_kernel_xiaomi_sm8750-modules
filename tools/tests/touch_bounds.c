/* SPDX-License-Identifier: GPL-2.0-only */
/* Exercise the actual driver's ABI length validator on a host compiler. */
#include <assert.h>
#include <stdint.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef int8_t s8;
typedef int32_t s32;
#include "xiaomi_touch_type_common.h"

int main(void)
{
	common_data_t data = { .cmd = SET_LONG_VALUE };

	data.data_len = 0;
	assert(xiaomi_touch_valid_data_len(&data));
	data.data_len = 256;
	assert(xiaomi_touch_valid_data_len(&data));
	data.data_len = 257;
	assert(!xiaomi_touch_valid_data_len(&data));
	data.data_len = 65535;
	assert(!xiaomi_touch_valid_data_len(&data));

	data.cmd = GET_THP_IC_CUR_VALUE;
	data.data_len = 0;
	assert(xiaomi_touch_valid_data_len(&data));
	data.data_len = 257;
	assert(xiaomi_touch_valid_data_len(&data));
	data.data_len = 1020;
	assert(xiaomi_touch_valid_data_len(&data));
	data.data_len = 1021;
	assert(!xiaomi_touch_valid_data_len(&data));
	data.data_len = 65535;
	assert(!xiaomi_touch_valid_data_len(&data));

	data.cmd = SET_THP_IC_CUR_VALUE;
	data.data_len = 0;
	assert(!xiaomi_touch_valid_data_len(&data));
	data.data_len = 1;
	assert(xiaomi_touch_valid_data_len(&data));
	data.data_len = 257;
	assert(xiaomi_touch_valid_data_len(&data));
	data.data_len = 1021;
	assert(xiaomi_touch_valid_data_len(&data));
	data.data_len = 1022;
	assert(!xiaomi_touch_valid_data_len(&data));
	data.data_len = 65535;
	assert(!xiaomi_touch_valid_data_len(&data));
	return 0;
}
