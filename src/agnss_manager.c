#include "agnss_manager.h"
#include "agnss_storage.h"
#include "agnss_vendor.h"
#include "ec800m.h"
#include "gps.h"
#include "fota.h"
#include "config.h"
#define AGNSS_BUFFER_SIZE 1024U
#define AGNSS_REFRESH_MS (2UL*60UL*60UL*1000UL)
#define AGNSS_RETRY_MS 60000UL
static gnss_type_t s_type,s_meta_type; static bool s_boot_pending,s_injected; static uint32_t s_last_attempt,s_retry_at,s_off,s_meta_seq,s_meta_len; static uint8_t s_buf[AGNSS_BUFFER_SIZE]; static agnss_inject_cb_t s_cb;
static bool ota_active(void){fota_state_t s=fota_get_state();return s==FOTA_STATE_CONNECTING||s==FOTA_STATE_DOWNLOADING||s==FOTA_STATE_VERIFYING;}
void agnss_init(gnss_type_t t){s_type=t;s_boot_pending=true;s_injected=false;s_last_attempt=0;s_retry_at=0;s_off=0;gnss_vendor_set_type(t);(void)agnss_storage_init();}
void agnss_set_inject_callback(agnss_inject_cb_t cb){s_cb=cb;}
bool agnss_has_injected(void){return s_injected;}
bool agnss_retry_due(uint32_t now){return (int32_t)(now-s_retry_at)>=0;}
void agnss_process(void){uint32_t now=TICK_MS();if(s_type==GNSS_TYPE_UNKNOWN||ota_active()||!ec800m_is_ready())return;if(!s_boot_pending&&(gps_is_valid()||(uint32_t)(now-s_last_attempt)<AGNSS_REFRESH_MS))return;if(!agnss_retry_due(now))return;if(!s_cb)s_cb=gnss_vendor_inject;agnss_meta_t m;if(!agnss_storage_get_latest(&m)||m.type!=(uint8_t)s_type){s_retry_at=now+AGNSS_RETRY_MS;return;}if(m.sequence!=s_meta_seq||m.length!=s_meta_len||m.type!=s_meta_type){s_meta_seq=m.sequence;s_meta_len=m.length;s_meta_type=(gnss_type_t)m.type;s_off=0;s_injected=false;}if(s_off>=m.length){if(!s_cb(s_type,NULL,0)){s_retry_at=now+AGNSS_RETRY_MS;return;}s_boot_pending=false;s_injected=true;s_last_attempt=now;return;}uint16_t n=(uint16_t)((m.length-s_off)>sizeof s_buf?sizeof s_buf:(m.length-s_off));if(!agnss_storage_read(s_off,s_buf,n)||!s_cb(s_type,s_buf,n)){s_retry_at=now+AGNSS_RETRY_MS;return;}s_off+=n;}

