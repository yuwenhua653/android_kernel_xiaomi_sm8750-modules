// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
#define DSI_BACKLIGHT_DCS 2
#define MIPI_DSI_DCS_READ 6
#define MIPI_DSI_MSG_REQ_ACK 1
#define MIPI_DSI_MSG_UNICAST_COMMAND 128
#define MIPI_DSI_MODE_LPM 2048
#define DSI_INFO(...) ((void)0)
#define DSI_WARN(...) ((void)0)
#define DSI_ERR(...) ((void)0)
#define unlikely(x) (x)
struct config {
    bool optin, needed;
    u64 id;
    u32 len;
    int size;
    u8 cmd[8];
    const char *state;
    int id_error, len_error;
};
struct dsi_parser_utils {
    const struct config *data;
    bool (*read_bool)(const struct config *, const char *);
    int (*read_u64)(const struct config *, const char *, u64 *);
    int (*read_u32)(const struct config *, const char *, u32 *);
    const void *(*get_property)(const struct config *, const char *, int *);
};
struct mipi_dsi_device { unsigned long mode_flags; u8 channel; };
struct dsi_panel {
    struct { bool enabled, build_id_attempted, build_id_valid; u8 build_id; } annibale;
    struct dsi_parser_utils utils;
    struct { bool ext_bridge_mode; } host_config;
    struct { int type; u32 bl_max_level, bl_dcs_subtype; bool lp_mode, bl_inverted_dbv; } bl_config;
    struct mipi_dsi_device mipi_device;
    bool panel_initialized;
    int esd_recovery_pending;
};
struct dsi_ctrl { bool secure_mode; };
struct dsi_display {
    struct dsi_panel *panel;
    bool trusted_vm_env, bypass;
    int ctrl_count;
    struct { struct dsi_ctrl *ctrl; } ctrl[2];
};
struct dsi_cmd_desc { struct {
    u8 type, channel;
    unsigned int flags;
    const void *tx_buf;
    void *rx_buf;
    size_t tx_len, rx_len;
} msg; };
static int reads, rx_result, delays, writes, write_result, host_error;
static u8 rx_revision;
static bool host_ready;
static u32 written;
static unsigned long write_flags;
static bool read_bool(const struct config *c, const char *key)
{ return !strcmp(key, "xiaomi,annibale-pb-quirks") ? c->optin : c->needed; }
static int read_u64(const struct config *c, const char *key, u64 *out)
{ assert(!strcmp(key,"mi,panel-id")); *out=c->id; return c->id_error; }
static int read_u32(const struct config *c, const char *key, u32 *out)
{ assert(!strcmp(key,"mi,panel-build-id-read-length")); *out=c->len; return c->len_error; }
static const void *get_property(const struct config *c, const char *key, int *size)
{
    if (strstr(key,"command-state")) return c->state;
    assert(strstr(key,"read-command")); *size=c->size; return c->size < 0 ? NULL : c->cmd;
}
static void usleep_range(unsigned int low, unsigned int high)
{ assert(low == 5000 && high == 5100); delays++; }
static int atomic_read(int *value) { return *value; }
static bool phy_pll_bypass(struct dsi_display *d) { return d->bypass; }
static int dsi_display_ctrl_get_host_init_state(struct dsi_display *d, bool *ready)
{ assert(d); *ready=host_ready; return host_error; }
static int dsi_display_cmd_rx_locked(struct dsi_display *d, struct dsi_cmd_desc *cmd)
{
    assert(cmd->msg.type == 6 && cmd->msg.channel == d->panel->mipi_device.channel);
    assert(cmd->msg.flags == (128|1));
    assert(cmd->msg.tx_len == 1 && cmd->msg.rx_len == 1);
    assert(*(u8 *)cmd->msg.tx_buf == 0xda);
    *(u8 *)cmd->msg.rx_buf = rx_revision; reads++; return rx_result;
}
static int mipi_dsi_dcs_set_display_brightness(struct mipi_dsi_device *d, u32 level)
{ writes++; written=level; write_flags=d->mode_flags; return write_result; }
static int mipi_dsi_dcs_subtype_set_display_brightness(struct mipi_dsi_device *d, u32 level, u32 subtype)
{ assert(subtype); return mipi_dsi_dcs_set_display_brightness(d,level); }
#include "display_under_test.inc"
static struct config valid_config(void)
{
    return (struct config){ .optin=true, .needed=true, .id=0x0050313150420d0aULL,
        .len=1, .size=8, .cmd={6,1,0,1,0,0,1,0xda}, .state="dsi_hs_mode" };
}
int main(void)
{
    struct config c=valid_config();
    struct dsi_panel p={ .utils={&c, read_bool, read_u64, read_u32, get_property},
        .bl_config={.type=DSI_BACKLIGHT_DCS,.bl_max_level=16383},
        .panel_initialized=true, .mipi_device={.channel=1} };
    struct dsi_ctrl ctrl={0};
    struct dsi_display d={.panel=&p,.ctrl_count=1,.ctrl={{&ctrl}}};
    assert(dsi_panel_parse_annibale(&p)==0 && p.annibale.enabled);
    for (int failure=0; failure<13; failure++) {
        c=valid_config(); p.host_config.ext_bridge_mode=false;
        p.bl_config.type=DSI_BACKLIGHT_DCS; p.bl_config.bl_max_level=16383;
        switch(failure) {
        case 0:c.id++; break; case 1:c.id_error=-EINVAL; break;
        case 2:c.needed=false; break; case 3:c.len=2; break;
        case 4:c.len_error=-EINVAL; break; case 5:c.size=7; break;
        case 6:c.cmd[7]=0xdb; break; case 7:c.state="dsi_lp_mode"; break;
        case 8:c.state=NULL; break; case 9:c.size=-1; break;
        case 10:p.host_config.ext_bridge_mode=true; break;
        case 11:p.bl_config.type=1; break; case 12:p.bl_config.bl_max_level=14; break;
        }
        assert(dsi_panel_parse_annibale(&p)==-EINVAL && !p.annibale.enabled);
        c.optin=false;
        assert(dsi_panel_parse_annibale(&p)==0 && !p.annibale.enabled);
    }
    c=valid_config(); p.bl_config.type=DSI_BACKLIGHT_DCS; p.bl_config.bl_max_level=16383;
    assert(dsi_panel_parse_annibale(&p)==0);
    for (unsigned id=0; id<256; id++) {
        p.annibale.build_id=id; p.annibale.build_id_valid=true;
        for (u32 value=0; value<=65535; value++) {
            assert(dsi_panel_annibale_backlight(&p,value)==
                ((id<128 && value && value<15) ? 15 : value));
        }
    }
    p.annibale.build_id=0; p.annibale.build_id_valid=false;
    assert(dsi_panel_annibale_backlight(&p,1)==1);
    dsi_panel_annibale_power_off_delay(&p); assert(delays==1);
    p.annibale.enabled=false; dsi_panel_annibale_power_off_delay(&p); assert(delays==1);
    p.annibale.build_id_valid=true; assert(dsi_panel_annibale_backlight(&p,1)==1);
    p.annibale.enabled=true;
    host_ready=true; rx_result=1; rx_revision=0x40;
    for (int gate=0; gate<9; gate++) {
        dsi_panel_annibale_invalidate(&p); reads=0;
        switch(gate) {
        case 0:p.annibale.enabled=false; break;
        case 1:p.panel_initialized=false; break;
        case 2:d.trusted_vm_env=true; break;
        case 3:d.bypass=true; break;
        case 4:p.esd_recovery_pending=1; break;
        case 5:ctrl.secure_mode=true; break;
        case 6:d.ctrl[0].ctrl=NULL; break;
        case 7:host_ready=false; break;
        case 8:host_error=-EIO; break;
        }
        dsi_display_annibale_read_build_id(&d);
        assert(!reads && !p.annibale.build_id_attempted && !p.annibale.build_id_valid);
        p.annibale.enabled=true; p.panel_initialized=true; d.trusted_vm_env=false;
        d.bypass=false; p.esd_recovery_pending=0; ctrl.secure_mode=false;
        d.ctrl[0].ctrl=&ctrl; host_ready=true; host_error=0;
    }
    int results[]={-EIO,0,2,1};
    for (unsigned i=0;i<sizeof(results)/sizeof(results[0]);i++) {
        dsi_panel_annibale_invalidate(&p); reads=0; rx_result=results[i];
        dsi_display_annibale_read_build_id(&d);
        assert(reads==1 && p.annibale.build_id_attempted);
        assert(p.annibale.build_id_valid==(rx_result==1));
        dsi_display_annibale_read_build_id(&d); assert(reads==1);
        if (rx_result==1) assert(p.annibale.build_id==0x40);
    }
    p.bl_config.bl_inverted_dbv=true; p.bl_config.lp_mode=true;
    p.mipi_device.mode_flags=0x20; write_result=-EIO;
    assert(dsi_panel_update_backlight(&p,1)==-EIO);
    assert(written==0x0f00 && write_flags==(0x20|MIPI_DSI_MODE_LPM));
    assert(p.mipi_device.mode_flags==0x20);
    assert(dsi_panel_update_backlight(&p,0)==-EIO && written==0);
    dsi_panel_annibale_invalidate(&p);
    assert(!p.annibale.build_id_valid && !p.annibale.build_id_attempted);
    assert(dsi_panel_update_backlight(&p,1)==-EIO && written==0x0100);
    int before=writes;
    assert(dsi_panel_update_backlight(&p,65536)==-EINVAL && writes==before);
    assert(dsi_panel_update_backlight(NULL,0)==-EINVAL);
    puts("PASS: P11 PB parser, all 256 revisions x 65536 levels, read gates/failures, DBV order and reset");
}
