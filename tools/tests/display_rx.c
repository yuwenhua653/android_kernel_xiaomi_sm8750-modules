// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
typedef uint32_t u32;
#define DSI_CTRL_CMD_READ 1
#define DSI_CORE_CLK 2
#define DSI_LINK_CLK 4
#define DSI_CLK_ON 1
#define DSI_CLK_OFF 0
#define DSI_DEBUG(...) ((void)0)
#define DSI_ERR(...) ((void)0)
struct dsi_panel { bool panel_initialized; };
struct dsi_ctrl { int unused; };
struct dsi_display_ctrl { struct dsi_ctrl *ctrl; };
struct dsi_display { struct dsi_panel *panel; struct dsi_display_ctrl ctrl[1];
    int cmd_master_idx, dsi_clk_handle; bool bypass; };
struct dsi_cmd_desc { u32 ctrl_flags; };
static int locked, clocks, interrupts=1, prepared, transfers;
static int clock_error, prepare_error, transfer_result;
static void dsi_panel_acquire_panel_lock(struct dsi_panel *p) { assert(p && !locked); locked=1; }
static void dsi_panel_release_panel_lock(struct dsi_panel *p) { assert(p && locked); locked=0; }
static bool phy_pll_bypass(struct dsi_display *d) { return d->bypass; }
static int dsi_display_clk_ctrl(int handle, int flags, int on)
{
    assert(locked && handle==7 && flags==(DSI_CORE_CLK|DSI_LINK_CLK));
    if (on) { assert(!clocks); if (clock_error) return clock_error; clocks=1; }
    else { assert(clocks && interrupts); clocks=0; }
    return 0;
}
static void dsi_display_toggle_error_interrupt_status(struct dsi_display *d, bool enabled)
{ assert(d && locked && clocks && interrupts!=enabled); interrupts=enabled; }
static void dsi_display_set_cmd_tx_ctrl_flags(struct dsi_display *d, struct dsi_cmd_desc *cmd)
{ assert(d && locked && clocks && !interrupts && cmd->ctrl_flags==DSI_CTRL_CMD_READ); }
static int dsi_ctrl_transfer_prepare(struct dsi_ctrl *c, u32 flags)
{ assert(c && flags==1 && !prepared); if (prepare_error) return prepare_error; prepared=1; return 0; }
static int dsi_ctrl_cmd_transfer(struct dsi_ctrl *c, struct dsi_cmd_desc *cmd, bool flush)
{ assert(c && cmd && !flush && prepared); transfers++; return transfer_result; }
static void dsi_ctrl_transfer_unprepare(struct dsi_ctrl *c, u32 flags)
{ assert(c && flags==1 && prepared); prepared=0; }
#include "display_rx_under_test.inc"
int main(void)
{
    struct dsi_panel p={.panel_initialized=true}; struct dsi_ctrl c={0};
    struct dsi_display d={.panel=&p,.ctrl={{&c}},.dsi_clk_handle=7};
    struct dsi_cmd_desc cmd={0};
    assert(dsi_display_cmd_rx(NULL,&cmd)==-EINVAL && !locked);
    d.panel=NULL; assert(dsi_display_cmd_rx(&d,&cmd)==-EINVAL && !locked); d.panel=&p;
    for (int scenario=0;scenario<7;scenario++) {
        p.panel_initialized=true; d.bypass=false; d.ctrl[0].ctrl=&c;
        clock_error=0; prepare_error=0; transfer_result=1; transfers=0;
        int expected=1;
        switch(scenario) {
        case 0:p.panel_initialized=false; expected=0; break;
        case 1:d.bypass=true; expected=0; break;
        case 2:d.ctrl[0].ctrl=NULL; expected=-EINVAL; break;
        case 3:clock_error=-EIO; expected=-EIO; break;
        case 4:prepare_error=-EAGAIN; expected=-EAGAIN; break;
        case 5:transfer_result=-EIO; expected=-EIO; break;
        }
        assert(dsi_display_cmd_rx(&d,&cmd)==expected);
        assert(!locked && !clocks && interrupts && !prepared);
        assert(transfers==(scenario>=5));
    }
    puts("PASS: actual DSI RX lock/clock/IRQ cleanup for skipped, failed and successful reads");
}
