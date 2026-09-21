"""Real cfg_query -> at_config -> F39 -> persistence and timer refresh."""
import re, subprocess, tempfile
from pathlib import Path
import test_at_config_serial_f39 as serial
ROOT=serial.ROOT
MAIN=r'''
#include "cfg_query.h"
#include "service_workspace.h"
static uint8_t *response;static const uint8_t *request;static int ack,rxlen;
static bool ack_fail;
bool ec800m_is_ready(void){return modem_ready;}
int ec800m_udp_txn_start(const char *h,uint16_t p,const uint8_t *t,uint16_t n,
 uint8_t *r,uint16_t cap,uint32_t timeout){
 (void)h;(void)p;(void)n;(void)cap;(void)timeout;request=t;response=r;return 0;
}
void ec800m_udp_txn_process(void){}
int ec800m_udp_txn_result(void){return rxlen;}
int ec800m_udp_send_once(const char *h,uint16_t p,const uint8_t *t,uint16_t n){
 (void)h;(void)p;assert(n==16&&t[2]==0x14);
 /* Match the real modem: a PDP restart prevents starting the ACK transaction. */
 assert(modem_ready);assert(saves>0);
 assert(!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA));
 ++ack;return ack_fail ? -1 : 0;
}
static int command(const char *s){
 console_len=0;unsigned n=strlen(s);cfg_query_init();assert(cfg_query_start()==0);
 cfg_query_process();memcpy(response,request,16);response[2]=0x92;
 response[3]=0;response[4]=21+n;response[13]=1;response[14]=3;
 memset(response+15,0,10);memcpy(response+15,"Pass",4);response[25]=n;
 memcpy(response+26,s,n);response[26+n]=0;
 for(unsigned i=0;i<26+n;i++)response[26+n]^=response[i];response[27+n]=13;
 rxlen=28+n;cfg_query_process();int r;assert(cfg_query_take_result(&r));return r;
}
int main(void){
 config.gnss_type=GNSS_TYPE_TAU804M;strcpy(config.pid,"12345678901");
 strcpy(config.terminal_model,"T360-A300");config.heartbeat_s=180;
 config.report_moving_s=30;config.report_stopped_s=180;config.server_port=9000;
 config.backup_port=7018;at_config_init();
 assert(command("hbt,120#")==0);assert(config.heartbeat_s==120&&saves==1&&ack==1);
 assert(refreshed_at_s==1234U);
 assert(command("\"HBT,240#\"")==0&&config.heartbeat_s==240&&ack==2);
 assert(command("DUALSET,IP:test.example,9999*FREQ:30,180#")==0);
 assert(config.server_port==9999&&config.backup_port==7018);
 int a=ack;device_config_t before=config;persist_ok=false;
 assert(command("hbt,300#")==-1&&ack==a&&!memcmp(&config,&before,sizeof config));
 persist_ok=true;assert(command("HBT,0#")==-1&&ack==a);
 assert(command("RELAY,1#")==-1&&ack==a); /* preserve relay safety rejection */
 const unsigned intervals[][2]={{60,300},{30,180},{20,120},{10,60}};
 for(unsigned i=0;i<4;i++){
   char text[40];sprintf(text,"FREQ,%u,%u#",intervals[i][0],intervals[i][1]);
   assert(command(text)==0&&config.report_moving_s==intervals[i][0]&&config.report_stopped_s==intervals[i][1]);
 }
 assert(command("APN,cmiot,,#")==0&&!config.autoapn_en&&!strcmp(config.apn,"cmiot"));
 assert(pdp_restarts==1&&!modem_ready);modem_ready=true;
 assert(command("APN,AUTO#")==0&&config.autoapn_en&&config.apn[0]==0);
 assert(pdp_restarts==2&&!modem_ready);modem_ready=true;
 /* Lost/delayed platform confirmation may redeliver the same command. */
 for(unsigned i=0;i<3;i++) {
   assert(command("APN,AUTO#")==0);
   assert(pdp_restarts==2&&modem_ready);
 }
 assert(pdp_restarts==2&&modem_ready);
 ack_fail=true;
 assert(command("APN,cmiot,user,pass#")==-1);
 assert(pdp_restarts==3&&!modem_ready&&!strcmp(config.apn_user,"user"));
 modem_ready=true;ack_fail=false;
 assert(command("APN,cmiot,user,pass#")==0&&pdp_restarts==3&&modem_ready);
 /* Credential-only changes still need the new profile applied. */
 assert(command("APN,cmiot,user,newpass#")==0&&pdp_restarts==4);
 modem_ready=true;
 assert(command("APN,cmiot,newuser,newpass#")==0&&pdp_restarts==5);
 modem_ready=true;
 a=ack;persist_ok=false;before=config;
 assert(command("APN,AUTO#")==-1&&ack==a&&pdp_restarts==5&&modem_ready);
 assert(!memcmp(&before,&config,sizeof config));persist_ok=true;
 assert(command("APN,,#")==-1&&ack==a&&pdp_restarts==5);
 /* APN idempotence must not suppress the other effects of an atomic command. */
 assert(command("DUALSET,APN:cmiot,newuser,newpass*FREQ:15,90#")==0);
 assert(pdp_restarts==5&&modem_ready&&config.report_moving_s==15&&config.report_stopped_s==90);
 assert(command("DUALSET,APN:AUTO*FREQ:20,120#")==0&&pdp_restarts==6);
 modem_ready=true;
 assert(command("DUALSET,APN:AUTO*FREQ:20,120#")==0&&pdp_restarts==6&&modem_ready);
 assert(command("hbt,120#")==0&&config.heartbeat_s==120&&modem_ready);
 return 0;
}
'''
def main():
    source=serial.HARNESS.replace('int main(void)', 'int serial_main(void)').replace(
        'g.hdop=1.2f;', 'g.hdop=1.2f; g.speed_kmh=30.0f;').replace(
        'void ec800m_restart_pdp(void) { }',
        'static bool modem_ready=true; static unsigned pdp_restarts;\n'
        'void ec800m_restart_pdp(void) { modem_ready=false; ++pdp_restarts; }')+MAIN
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);(p/'h.c').write_text(source)
        (p/'n32l40x.h').write_text('#pragma once\n#define GPIOA ((void*)0)\n#define GPIO_PIN_12 12U\n#define Bit_RESET 0\nint GPIO_ReadInputDataBit(void*,unsigned);\nvoid NVIC_SystemReset(void);\n')
        files=['plate_encoding.c','at_config.c','f39_command.c','f39_config_adapter.c','f39_reply.c',
               'sms_command.c','terminal_identity.c','cfg_query.c','service_workspace.c']
        subprocess.run([serial.compiler(),'-std=c99','-Wall','-Wextra','-Werror',
            '-Wno-misleading-indentation','-I',str(p),'-I',str(ROOT/'include'),str(p/'h.c')]+
            [str(ROOT/'src'/f) for f in files]+['-lm','-o',str(p/'h.exe')],check=True)
        subprocess.run([str(p/'h.exe')],check=True)
    print('cfg query F39 integration: PASS')
if __name__=='__main__':main()
