"""Actual JT808 RX -> params -> encoded ACK/query/registration on both channels."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import re

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('dual',Path(__file__).with_name('test_jt808_dual_session.py'))
dual=importlib.util.module_from_spec(spec);spec.loader.exec_module(dual)

def main():
    source=dual.HARNESS
    start=source.index('void jt808_params_handle_set(')
    end=source.index('jt808_terminal_info_result_t jt808_terminal_info_encode(',start)
    source=source[:start]+source[end:]
    source=source.replace('int main(void)', 'int original_main(void)')
    source+=r'''
static unsigned reconnect_requests;
void tcp_manager_request_reconnect(void) { ++reconnect_requests; }
uint32_t work_mode_sleep_monotonic_s(void) { return g_tick_ms/1000U; }
void work_mode_config_changed(const device_config_t *c,uint32_t now) { (void)c;(void)now; }
int main(void) {
    jt808_terminal_t terminal={0};uint8_t decoded[1024];uint16_t sn,len;
    strcpy(terminal.manufacturer_id,"70110");strcpy(terminal.terminal_model,"T360-A300");terminal.color=1;
    memset(&cfg,0,sizeof cfg);strcpy(cfg.pid,"56789012345");cfg.server_port=8898;
    cfg.heartbeat_s=180;cfg.report_moving_s=30;cfg.report_stopped_s=60;
    open_ch[0]=open_ch[3]=true;
    for (unsigned ch=0;ch<=3;ch+=3) {
        strcpy(cfg.auth_code,"AUTH");strcpy(cfg.backup_auth_code,"AUTH");
        jt808_init(&terminal);jt808_set_terminal_profile(NULL,cfg.plate_no);jt808_process();
        for(unsigned x=0;x<=3;x+=3){assert(msg(x,&sn,decoded,&len)==0x0102);auth_resp(x,sn,0);}
        /* User's 37-byte body, with the terminal identity supplied by the
         * synthetic harness rather than retaining a real device identifier. */
        const uint8_t location[]={4,0,0,0,0x29,4,0,0,0,30,
            0,0,0,0x27,4,0,0,0,180,0,0,0,0x20,4,0,0,0,0,
            0,0,0,0x21,4,0,0,0,0};
        inject(ch,0x8103,location,sizeof location);
        assert(msg(ch,&sn,decoded,&len)==1&&decoded[16]==0);
        assert(cfg.report_moving_s==30&&cfg.report_stopped_s==180);
        const uint8_t location_query[]={4,0,0,0,0x29,0,0,0,0x27,0,0,0,0x20,0,0,0,0x21};
        inject(ch,0x8106,location_query,sizeof location_query);
        assert(msg(ch,&sn,decoded,&len)==0x0104&&decoded[14]==4);
        assert(!memcmp(decoded+15,location+1,sizeof location-1));
        const uint8_t speed[]={1,0,0,0,0x55,4,0,0,0,100};
        inject(ch,0x8103,speed,sizeof speed);
        assert(msg(ch,&sn,decoded,&len)==1&&decoded[16]==0&&cfg.speed_limit_kmh==100);
        const uint8_t set[]={5,0,0,0,1,4,0,0,0,120,0,0,0,0x81,2,0,44,
            0,0,0,0x82,2,1,44,0,0,0,0x84,1,2,0,0,0,0x83,8,0xd4,0xc1,'B','1','2','3','4','5'};
        unsigned other=ch==0?3:0, old_sends=sends[other];
        inject(ch,0x8103,set,sizeof set);
        assert(msg(ch,&sn,decoded,&len)==1&&decoded[16]==0);
        assert(sends[other]==old_sends&&cfg.heartbeat_s==120);
        strcpy(cfg.auth_code,"AUTH");strcpy(cfg.backup_auth_code,"AUTH");
        jt808_init(&terminal);jt808_set_terminal_profile(NULL,cfg.plate_no);jt808_process();
        for(unsigned x=0;x<=3;x+=3){assert(msg(x,&sn,decoded,&len)==0x0102);auth_resp(x,sn,0);}
        const uint8_t q[]={2,0,0,0,1,0,0,0,0x83};
        inject(ch,0x8106,q,sizeof q);
        assert(msg(ch,&sn,decoded,&len)==0x0104);
        assert(decoded[12]==0x12&&decoded[13]==0x34&&decoded[14]==2);
        assert(!memcmp(decoded+20,(uint8_t[]){0,0,0,120},4));
        assert(!memcmp(decoded+29,set+sizeof(set)-8,8));
        inject(ch,0x8104,NULL,0);assert(msg(ch,&sn,decoded,&len)==0x0104);
        assert(decoded[14]==18);
        assert(jt808_send_register_to(ch)==0);assert(msg(ch,&sn,decoded,&len)==0x0100);
        assert(!memcmp(decoded+12,(uint8_t[]){0,44,1,44},4));assert(decoded[48]==2);
        assert(!memcmp(decoded+49,set+sizeof(set)-8,8));
    }
    return 0;
}
'''
    with tempfile.TemporaryDirectory() as d:
        p=Path(d);(p/'h.c').write_text(source,encoding='ascii')
        (p/'n32l40x.h').write_text('#pragma once\n#define GPIOA ((void*)0)\n#define GPIO_PIN_12 12U\n#define Bit_RESET 0\nint GPIO_ReadInputDataBit(void*,unsigned);\n')
        cmd=[dual.compiler(),'-std=c99','-Wall','-Wextra','-Werror','-I',str(p),'-I',str(ROOT/'include'),str(p/'h.c')]
        cmd += [str(ROOT/'src'/s) for s in ['jt808.c','jt808_session.c','terminal_identity.c','jt808_params.c','service_workspace.c']]
        subprocess.run(cmd+['-lm','-o',str(p/'h.exe')],check=True)
        subprocess.run([str(p/'h.exe')],check=True)
    print('test_jt808_params_wire: PASS')
if __name__=='__main__':main()
