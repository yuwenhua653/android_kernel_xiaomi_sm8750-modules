// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
typedef int8_t s8;
#define INVAILD_TEMPERATURE 1000
#define SET_CUR_VALUE 1
#define THP_TEMPERATURE_STATUS 2
#define POWER_SUPPLY_PROP_TEMP 3
#define LOG_INFO(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
#define READ_ONCE(x) atomic_load(&(x))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((long)(intptr_t)(p))
#define atomic_read(p) atomic_load(p)
#define atomic_set(p,v) atomic_store(p,v)
struct mutex { pthread_mutex_t native; };
static struct mutex xiaomi_temperature_lock={PTHREAD_MUTEX_INITIALIZER};
static struct mutex xiaomi_temperature_lifecycle_lock={PTHREAD_MUTEX_INITIALIZER};
static _Thread_local bool disabling;
static atomic_int disable_attempted, disable_done;
static void mutex_lock(struct mutex *m)
{
    if (disabling && m==&xiaomi_temperature_lock) atomic_store(&disable_attempted,1);
    assert(!pthread_mutex_lock(&m->native));
}
static void mutex_unlock(struct mutex *m) { assert(!pthread_mutex_unlock(&m->native)); }
struct queue { pthread_mutex_t lock; pthread_cond_t cond; unsigned epoch; atomic_int sleeping, timed; };
struct task_struct;
typedef struct { s8 touch_id; struct queue temp_detect_wait_queue;
    atomic_int temp_detect_ready; struct task_struct *temp_thread; } xiaomi_touch_data_t;
typedef struct { struct { int (*set_thermal_temp)(int,bool); } hardware_operation;
    struct { int temp_change_value; } hardware_param; } xiaomi_touch_driver_param_t;
static xiaomi_touch_data_t panels[2];
static xiaomi_touch_driver_param_t params[2];
static struct { atomic_int charging_status; } xiaomi_touch;
static xiaomi_touch_data_t *get_xiaomi_touch_data(s8 id) { return id>=0&&id<2 ? &panels[id] : NULL; }
static xiaomi_touch_driver_param_t *get_xiaomi_touch_driver_param(s8 id) { return id>=0&&id<2 ? &params[id] : NULL; }
struct task_struct { pthread_t thread; atomic_bool stop; int (*fn)(void *); void *data; };
static _Thread_local struct task_struct *current;
static bool create_failure;
static atomic_int joins;
static bool kthread_should_stop(void) { return current && atomic_load(&current->stop); }
static void *entry(void *p) { current=p; current->fn(current->data); return NULL; }
static struct task_struct *kthread_create(int (*fn)(void *),void *data,const char *fmt,int id)
{
    assert(fmt && id>=0 && id<2);
    if(create_failure)return (void *)(intptr_t)-ENOMEM;
    struct task_struct *p=calloc(1,sizeof(*p));assert(p);p->fn=fn;p->data=data;return p;
}
static void wake_up_process(struct task_struct *p) { assert(!pthread_create(&p->thread,NULL,entry,p)); }
static void wake_up_interruptible(struct queue *q)
{ pthread_mutex_lock(&q->lock);pthread_cond_broadcast(&q->cond);pthread_mutex_unlock(&q->lock); }
static int kthread_stop(struct task_struct *p)
{
    assert(p && !IS_ERR(p));atomic_store(&p->stop,true);
    xiaomi_touch_data_t *touch=p->data;wake_up_interruptible(&touch->temp_detect_wait_queue);
    assert(!pthread_join(p->thread,NULL));atomic_fetch_add(&joins,1);free(p);return 0;
}
#define wait_event_interruptible(q,condition) ({ \
    pthread_mutex_lock(&(q).lock); \
    while(!(condition)) { atomic_fetch_add(&(q).sleeping,1); \
        pthread_cond_wait(&(q).cond,&(q).lock);atomic_fetch_sub(&(q).sleeping,1); } \
    pthread_mutex_unlock(&(q).lock);0; })
static atomic_int last_delay;
static int msecs_to_jiffies(int delay) { assert(delay==5000||delay==10000);atomic_store(&last_delay,delay);return delay; }
#define wait_event_interruptible_timeout(q,condition,timeout) do { \
    (void)(timeout);pthread_mutex_lock(&(q).lock);unsigned seq=(q).epoch; \
    while(!(condition)&&(q).epoch==seq) { atomic_fetch_add(&(q).timed,1); \
        pthread_cond_wait(&(q).cond,&(q).lock);atomic_fetch_sub(&(q).timed,1); } \
    pthread_mutex_unlock(&(q).lock); } while(0)
struct power_supply { atomic_int exists,error,temp,refs,gets,puts; };
static struct power_supply battery,bms;
union power_supply_propval { int intval; };
static struct power_supply *power_supply_get_by_name(const char *name)
{
    struct power_supply *p=!strcmp(name,"battery")?&battery:&bms;
    if(!atomic_load(&p->exists))return NULL;
    atomic_fetch_add(&p->refs,1);atomic_fetch_add(&p->gets,1);return p;
}
static int power_supply_get_property(struct power_supply *p,int prop,union power_supply_propval *value)
{ assert(prop==POWER_SUPPLY_PROP_TEMP);value->intval=atomic_load(&p->temp);return atomic_load(&p->error); }
static void power_supply_put(struct power_supply *p)
{ assert(atomic_fetch_sub(&p->refs,1)>0);atomic_fetch_add(&p->puts,1); }
static atomic_int calls[2], notices[2], callback_error, blocked, entered, finished, notice_value[2];
static pthread_mutex_t cb_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cb_cond=PTHREAD_COND_INITIALIZER;
static int callback(int id,int temp,bool force)
{
    assert(!force && temp>-100 && temp<100);atomic_fetch_add(&calls[id],1);
    pthread_mutex_lock(&cb_lock);atomic_store(&entered,1);
    while(atomic_load(&blocked))pthread_cond_wait(&cb_cond,&cb_lock);
    atomic_store(&finished,1);pthread_mutex_unlock(&cb_lock);return atomic_load(&callback_error);
}
static int callback0(int temp,bool force) { return callback(0,temp,force); }
static int callback1(int temp,bool force) { return callback(1,temp,force); }
static void add_common_data_to_buf(s8 id,int operation,int type,int count,int *value)
{ assert(id>=0&&id<2&&operation==1&&type==2&&count==1);atomic_store(&notice_value[id],*value);atomic_fetch_add(&notices[id],1); }
#include "power_under_test.inc"
static void until(atomic_int *value,int expected) { while(atomic_load(value)<expected)sched_yield(); }
static void tick(int id)
{
    struct queue *q=&panels[id].temp_detect_wait_queue;until(&q->timed,1);
    pthread_mutex_lock(&q->lock);q->epoch++;pthread_cond_broadcast(&q->cond);pthread_mutex_unlock(&q->lock);
}
static void *disable(void *unused)
{ (void)unused;disabling=true;xiaomi_set_temperature_detection(0,false);assert(atomic_load(&finished));atomic_store(&disable_done,1);return NULL; }
int main(void)
{
    alarm(15);
    for(int id=0;id<2;id++) {
        panels[id].touch_id=id;pthread_mutex_init(&panels[id].temp_detect_wait_queue.lock,NULL);
        pthread_cond_init(&panels[id].temp_detect_wait_queue.cond,NULL);
        params[id].hardware_param.temp_change_value=2;
        params[id].hardware_operation.set_thermal_temp=id?callback1:callback0;
    }
    assert(!xiaomi_touch_temp_valid(INT_MIN)&&!xiaomi_touch_temp_valid(INT_MAX));
    assert(!xiaomi_touch_temp_valid(-1000)&&!xiaomi_touch_temp_valid(1000));
    for(int t=-999;t<=999;t++) {
        assert(xiaomi_touch_temp_valid(t));
        int rounded=(abs(t)+5)/10;if(t<0)rounded=-rounded;
        assert(xiaomi_touch_temp_degrees(t)==rounded);
    }
    for(int a=0;a<3;a++)for(int b=0;b<3;b++) {
        atomic_store(&battery.exists,a!=0);atomic_store(&battery.error,a==2?-EIO:0);atomic_store(&battery.temp,257);
        atomic_store(&bms.exists,b!=0);atomic_store(&bms.error,b==2?-EIO:0);atomic_store(&bms.temp,-55);
        int expected=a?(a==2?-1000:257):(b==1?-55:-1000);
        assert(get_bms_temp_common()==expected);assert(!atomic_load(&battery.refs)&&!atomic_load(&bms.refs));
    }
    assert(atomic_load(&battery.gets)==atomic_load(&battery.puts));
    assert(atomic_load(&bms.gets)==atomic_load(&bms.puts));
    atomic_store(&battery.exists,1);atomic_store(&battery.error,0);atomic_store(&battery.temp,-55);
    xiaomi_stop_temperature_detection(-1);xiaomi_stop_temperature_detection(0);
    create_failure=true;xiaomi_start_temperature_detection(&panels[0]);
    assert(!panels[0].temp_thread&&!atomic_load(&panels[0].temp_detect_ready));
    xiaomi_stop_temperature_detection(0);create_failure=false;
    atomic_store(&callback_error,-EIO);xiaomi_start_temperature_detection(&panels[0]);
    until(&calls[0],1);until(&panels[0].temp_detect_wait_queue.timed,1);assert(!atomic_load(&notices[0]));
    atomic_store(&callback_error,0);tick(0);until(&notices[0],1);assert(atomic_load(&notice_value[0])==-6);
    /* Invalid sensor data must not invoke the firmware callback or poison its cache. */
    int old_calls=atomic_load(&calls[0]), old_gets=atomic_load(&battery.gets);
    atomic_store(&battery.temp,INT_MIN);tick(0);until(&battery.gets,old_gets+1);
    until(&panels[0].temp_detect_wait_queue.timed,1);assert(atomic_load(&calls[0])==old_calls);
    atomic_store(&battery.temp,-55);
    xiaomi_start_temperature_detection(&panels[1]);until(&notices[1],1);assert(atomic_load(&notice_value[1])==-6);
    xiaomi_stop_temperature_detection(1);int prior=atomic_load(&joins);
    xiaomi_stop_temperature_detection(1);assert(atomic_load(&joins)==prior);
    /* Pause drains a callback that is already inside the firmware operation. */
    atomic_store(&entered,0);atomic_store(&finished,0);atomic_store(&blocked,1);
    atomic_store(&battery.temp,125);tick(0);until(&entered,1);
    pthread_t pauser;assert(!pthread_create(&pauser,NULL,disable,NULL));until(&disable_attempted,1);
    assert(!atomic_load(&disable_done));
    pthread_mutex_lock(&cb_lock);atomic_store(&blocked,0);pthread_cond_broadcast(&cb_cond);pthread_mutex_unlock(&cb_lock);
    assert(!pthread_join(pauser,NULL));until(&panels[0].temp_detect_wait_queue.sleeping,1);
    prior=atomic_load(&calls[0]);xiaomi_stop_temperature_detection(0);assert(atomic_load(&calls[0])==prior);
    xiaomi_set_temperature_detection(0,true);assert(!atomic_load(&panels[0].temp_detect_ready));
    /* Restart obtains a new per-instance cache and stop wakes the timed wait. */
    atomic_store(&xiaomi_touch.charging_status,1);xiaomi_start_temperature_detection(&panels[0]);
    until(&calls[0],prior+1);until(&panels[0].temp_detect_wait_queue.timed,1);assert(atomic_load(&last_delay)==5000);
    xiaomi_stop_temperature_detection(0);assert(!atomic_load(&battery.refs)&&!atomic_load(&bms.refs));
    assert(atomic_load(&battery.gets)==atomic_load(&battery.puts));
    for(int cycle=0;cycle<16;cycle++) {
        int id=cycle%2, count=atomic_load(&notices[id]);
        xiaomi_start_temperature_detection(&panels[id]);until(&notices[id],count+1);
        xiaomi_set_temperature_detection(id,false);
        until(&panels[id].temp_detect_wait_queue.sleeping,1);
        xiaomi_stop_temperature_detection(id);assert(!panels[id].temp_thread);
    }
    puts("PASS: battery references, signed temperature, two workers, failed command retry, pause drain, idle/timed stop and restart");
}
