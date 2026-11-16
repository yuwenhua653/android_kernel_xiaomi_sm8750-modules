// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define CONFIG_DRM 1
#define CONFIG_QCOM_PANEL_EVENT_NOTIFIER 1
#define IS_ENABLED(x) (x)
#define EPROBE_DEFER 517
#define MAX_TOUCH_PANEL_COUNT 2
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define IS_ERR_OR_NULL(p) (!(p) || IS_ERR(p))
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define PTR_ERR(p) ((intptr_t)(p))
#define container_of(p, type, member) ((type *)((char *)(p) - offsetof(type, member)))
#define LOG_DEBUG(...) ((void)0)
#define LOG_INFO(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
typedef int8_t s8;
struct drm_panel { int unused; };
struct device_node { int refs, count, error; struct device_node *child[2]; struct drm_panel panel; };
struct device { struct device_node *of_node; };
struct work_struct { void (*fn)(struct work_struct *); bool pending; };
struct delayed_work { struct work_struct work; };
struct workqueue_struct { int queued; };
typedef struct {
    struct delayed_work panel_notifier_register_work;
    struct work_struct suspend_work, resume_work;
    struct device *dev;
    struct workqueue_struct *event_wq;
    void *notifier_cookie;
    int panel_event_notifier_tag, panel_event_notifier_client;
    bool panel_notifier_active;
} xiaomi_touch_data_t;
static struct { xiaomi_touch_data_t xiaomi_touch_data[2]; } xiaomi_touch;
static int xiaomi_panel_lifecycle_lock, xiaomi_panel_work_lock;
static int reg_error, registrations, unregistrations, cancels, scheduled;
static bool inject_late_callback;
static char cookie[2];
static void mutex_lock(int *p) { assert(!*p); *p = 1; }
static void mutex_unlock(int *p) { assert(*p); *p = 0; }
static xiaomi_touch_data_t *get_xiaomi_touch_data(s8 id)
{ return id >= 0 && id < 2 ? &xiaomi_touch.xiaomi_touch_data[id] : NULL; }
#define INIT_WORK(w, f) do { (w)->fn = (f); (w)->pending = false; } while (0)
#define INIT_DELAYED_WORK(w, f) INIT_WORK(&(w)->work, f)
static unsigned int msecs_to_jiffies(unsigned int value) { return value; }
static int schedule_delayed_work(struct delayed_work *w, unsigned int delay)
{ assert(w->work.fn); w->work.pending = true; scheduled++; return 1; }
static int of_count_phandle_with_args(struct device_node *n, const char *p, void *unused)
{ assert(!strcmp(p, "panel")); return n->count; }
static struct device_node *of_parse_phandle(struct device_node *n, const char *p, int i)
{ struct device_node *child = n->child[i]; if (child) child->refs++; return child; }
static struct drm_panel *of_drm_find_panel(struct device_node *n)
{ assert(n); return n->error ? ERR_PTR(n->error) : &n->panel; }
static void of_node_put(struct device_node *n) { if (n) { assert(n->refs > 0); n->refs--; } }
static void xiaomi_drm_panel_notifier_callback(void) {}
static void xiaomi_touch_suspend_work(struct work_struct *w) {}
static void xiaomi_touch_resume_work(struct work_struct *w) {}
static void *panel_event_notifier_register(int tag, int client, struct drm_panel *p,
                                         void (*callback)(void), void *data)
{ assert(p && callback); registrations++; return reg_error ? ERR_PTR(reg_error) : &cookie[client]; }
static void flush_workqueue(struct workqueue_struct *w) { assert(w); }
static bool queue_work(struct workqueue_struct *w, struct work_struct *work)
{ assert(work->fn); w->queued++; work->pending = true; return true; }
void schedule_resume_suspend_work(s8 id, bool resume);
static void panel_event_notifier_unregister(void *p)
{
    int id = p == &cookie[0] ? 0 : 1;
    assert(p && !IS_ERR(p));
    assert(!xiaomi_touch.xiaomi_touch_data[id].panel_notifier_active);
    unregistrations++;
    if (inject_late_callback) schedule_resume_suspend_work(id, true);
}
static void cancel_delayed_work_sync(struct delayed_work *w)
{ assert(w->work.fn); w->work.pending = false; }
static void cancel_work_sync(struct work_struct *w)
{ assert(w->fn); w->pending = false; cancels++; }
struct power_supply { int present, error, online, refs; };
static struct power_supply wireless, usb;
union power_supply_propval { int intval; };
#define POWER_SUPPLY_PROP_ONLINE 0
#define NOT_CHARGING 0
#define CHARGING 1
#define WIRELESS_CHARGING 2
#define WIRED_CHARGING 4
static struct power_supply *power_supply_get_by_name(const char *name)
{
    struct power_supply *p = !strcmp(name, "wireless") ? &wireless : &usb;
    if (!p->present)
        return NULL;
    p->refs++;
    return p;
}
static int power_supply_get_property(struct power_supply *p, int prop, union power_supply_propval *v)
{ if (p->error) return p->error; v->intval = p->online; return 0; }
static void power_supply_put(struct power_supply *p) { assert(p->refs > 0); p->refs--; }

#include "touch_under_test.inc"

static void run_worker(int id)
{
    struct delayed_work *w = &xiaomi_touch.xiaomi_touch_data[id].panel_notifier_register_work;
    assert(w->work.pending); w->work.pending = false; w->work.fn(&w->work);
}

int main(void)
{
    struct device_node panels[2] = {{.error = -EPROBE_DEFER}, {.error = -EPROBE_DEFER}};
    struct device_node roots[2] = {{.count = 2, .child = {NULL, &panels[0]}},
                                  {.count = 1, .child = {&panels[1]}}};
    struct device dev[2] = {{&roots[0]}, {&roots[1]}};
    struct workqueue_struct queues[2] = {{0}, {0}};
    for (int i = 0; i < 2; i++) xiaomi_touch.xiaomi_touch_data[i].event_wq = &queues[i];
    xiaomi_unregister_panel_notifier(&dev[0], 0); /* Never initialized: no cancel. */
    assert(!cancels);
    for (int i = 0; i < 2; i++) xiaomi_register_panel_notifier(&dev[i], i, 1, i);
    for (int repeat = 0; repeat < 12; repeat++) {
        run_worker(0); run_worker(1); /* No shared retry ceiling. */
        assert(!panels[0].refs && !panels[1].refs);
    }
    panels[0].error = 0;
    run_worker(0);
    assert(xiaomi_touch.xiaomi_touch_data[0].notifier_cookie == &cookie[0]);
    assert(!xiaomi_touch.xiaomi_touch_data[0].panel_notifier_register_work.work.pending);
    int before = scheduled;
    xiaomi_register_panel_notifier(&dev[0], 0, 1, 0); /* Duplicate cannot reinit live work. */
    assert(before == scheduled);
    schedule_resume_suspend_work(0, true);
    assert(queues[0].queued == 1);
    inject_late_callback = true;
    xiaomi_unregister_panel_notifier(&dev[0], 0);
    assert(unregistrations == 1 && cancels == 2 && queues[0].queued == 1);
    schedule_resume_suspend_work(0, false); /* Copied callback after unregister returns. */
    assert(queues[0].queued == 1);
    xiaomi_unregister_panel_notifier(&dev[0], 0); /* Idempotent. */
    assert(unregistrations == 1 && cancels == 2);
    xiaomi_unregister_panel_notifier(&dev[0], 1); /* Wrong device cannot stop panel 1. */
    assert(xiaomi_touch.xiaomi_touch_data[1].panel_notifier_active);
    xiaomi_unregister_panel_notifier(&dev[1], 1);
    assert(!xiaomi_touch.xiaomi_touch_data[1].panel_notifier_register_work.work.pending);
    assert(!xiaomi_touch.xiaomi_touch_data[1].notifier_cookie);
    panels[1].error = 0;
    xiaomi_register_panel_notifier(&dev[1], 1, 1, 1);
    reg_error = -ENOMEM;
    run_worker(1);
    assert(xiaomi_touch.xiaomi_touch_data[1].panel_notifier_register_work.work.pending);
    assert(!xiaomi_touch.xiaomi_touch_data[1].notifier_cookie && !panels[1].refs);
    reg_error = -EEXIST;
    run_worker(1);
    assert(!xiaomi_touch.xiaomi_touch_data[1].panel_notifier_register_work.work.pending);
    xiaomi_unregister_panel_notifier(&dev[1], 1);
    assert(unregistrations == 1); /* Never unregister somebody else's cookie. */
    roots[1].count = -EINVAL;
    xiaomi_register_panel_notifier(&dev[1], 1, 1, 1);
    run_worker(1);
    assert(!xiaomi_touch.xiaomi_touch_data[1].panel_notifier_register_work.work.pending);
    xiaomi_unregister_panel_notifier(&dev[1], 1);
    roots[1].count = 1; reg_error = 0;
    xiaomi_register_panel_notifier(&dev[1], 1, 1, 1);
    run_worker(1);
    assert(xiaomi_touch.xiaomi_touch_data[1].notifier_cookie == &cookie[1]);
    xiaomi_unregister_panel_notifier(&dev[1], 1);
    assert(!panels[0].refs && !panels[1].refs);
    for (int wp = 0; wp < 2; wp++) for (int up = 0; up < 2; up++)
    for (int we = 0; we < 2; we++) for (int ue = 0; ue < 2; ue++)
    for (int wo = 0; wo < 2; wo++) for (int uo = 0; uo < 2; uo++) {
        wireless = (struct power_supply){wp, we ? -EIO : 0, wo, 0};
        usb = (struct power_supply){up, ue ? -EIO : 0, uo, 0};
        int expected = wp && !we && wo ? CHARGING | WIRELESS_CHARGING :
                       up && !ue && uo ? CHARGING | WIRED_CHARGING : NOT_CHARGING;
        assert(xiaomi_get_charging_status() == expected);
        assert(!wireless.refs && !usb.refs);
    }
    puts("PASS: late panel/rebind, cancellation callbacks, DT references and 64 charging cases");
    return 0;
}
