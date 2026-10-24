"""Real JT808 wire scenarios for response correlation and malformed downlinks."""
import test_jt808_dual_session as dual
prefix=dual.HARNESS.split('int main(void) {')[0]
prefix=prefix.replace('uint8_t raw[256], framed[512]', 'uint8_t raw[512], framed[1030]')
prefix=prefix.replace('static void inject(uint8_t', 'static uint16_t injected_flags;\nstatic void inject(uint8_t')
prefix=prefix.replace('(uint8_t)(body_len>>8);raw[p++]=(uint8_t)body_len;', '(uint8_t)((body_len|injected_flags)>>8);raw[p++]=(uint8_t)body_len;')
main=r"""
int main(void) {
 (void)test_rx_overlap; (void)reg_resp; (void)auth_resp; (void)query;
 jt808_terminal_t terminal={0};uint8_t d[1024],body[300];uint16_t sn,n;
 strcpy(cfg.pid,"56789012345");cfg.heartbeat_s=60;
 memcpy(terminal.manufacturer_id,"CYHLL",5);strcpy(terminal.terminal_model,"A300_406");
 open_ch[0]=true;generation[0]=1;
 /* 257 auth bytes must not wrap to one byte and become a valid auth code. */
 jt808_init(&terminal);jt808_process();assert(msg(0,&sn,d,&n)==0x0100);
 body[0]=(uint8_t)(sn>>8);body[1]=(uint8_t)sn;body[2]=0;
 memset(body+3,'A',257);inject(0,0x8100,body,260);jt808_process();
 assert(auth_store_calls[0]==0 && cfg.auth_code[0]==0);
 /* An embedded NUL must not persist a silently shortened code. */
 jt808_init(&terminal);g_tick_ms+=60000;jt808_process();assert(msg(0,&sn,d,&n)==0x0100);
 body[0]=(uint8_t)(sn>>8);body[1]=(uint8_t)sn;body[2]=0;
 memcpy(body+3,"A\0B",3);inject(0,0x8100,body,6);jt808_process();
 assert(auth_store_calls[0]==0 && cfg.auth_code[0]==0);
 /* A clean registration/authentication after rejection remains possible. */
 jt808_init(&terminal);g_tick_ms+=60000;jt808_process();assert(msg(0,&sn,d,&n)==0x0100);
 reg_resp(0,sn,"CLEAN");jt808_process();assert(msg(0,&sn,d,&n)==0x0102);
 auth_resp(0,sn,0);assert(jt808_channel_online(0));
 /* 8107 and 8201 have empty request bodies. Reject trailing data. */
 uint8_t extra=1;inject(0,0x8107,&extra,1);
 assert(msg(0,&sn,d,&n)==1 && d[14]==0x81 && d[15]==7 && d[16]==2);
 inject(0,0x8201,&extra,1);assert(msg(0,&sn,d,&n)==1 && d[16]==2);
 /* Unsupported encryption/version/reserved/subpackage flags cannot execute. */
 for(unsigned i=10;i<16;i++) {
  unsigned before=sends[0];injected_flags=(uint16_t)(1U<<i);
  query(0,0x8107);assert(sends[0]==before);
 }
 injected_flags=0;
 /* A valid maximum-size prefix followed by junk is an invalid whole frame. */
 uint8_t long_frame[515]; maximum_rx_frame(long_frame,0x11,0x21);
 long_frame[513]=0x55;long_frame[514]=0x7e;
 unsigned before=sends[0];jt808_on_recv(0,long_frame,515);
 assert(sends[0]==before);
 query(0,0x8107);assert(sends[0]==before+1); /* next delimiter recovers */
 gps.valid=true;gps.fix_quality=1;gps.lat=10;gps.lon=20;
 gps.year=2026;gps.month=10;gps.day=21;gps.hour=1;gps.last_update_ms=g_tick_ms;
 cfg.mileage_m=123400;
 query(0,0x8201);assert(msg(0,&sn,d,&n)==0x0201);
 assert(d[12]==0x12 && d[13]==0x34); /* request SN, not response header SN */
 assert(n==13+2+67 && (((d[2]&3)<<8)|d[3])==69);
 assert(d[14+28]==1 && d[14+29]==4);
 assert(d[14+32]==4 && d[14+33]==0xd2);
 return 0;
}
"""
dual.HARNESS=prefix+main
if __name__=='__main__':raise SystemExit(dual.main())
