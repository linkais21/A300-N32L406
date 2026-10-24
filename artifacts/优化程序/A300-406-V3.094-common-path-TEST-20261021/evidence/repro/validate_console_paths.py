"""Compare real debug-console outputs and setter arguments across snapshots."""
from pathlib import Path
import runpy, tempfile, subprocess, json, hashlib
m=runpy.run_path(str(Path(__file__).with_name('validate_common_paths.py')))
OUT=m['OUT']

EXTRA=r'''
static void dump(const void *v,size_t n) {
 const unsigned char *p=v;for(size_t i=0;i<n;++i)printf("%02x",p[i]);putchar('|');
}
int main(void) {
 char input[256];unsigned cases=0;
 assert(original_main()==0);
 while(fgets(input,sizeof input,stdin)) {
  input[strcspn(input,"\n")]=0;
  for(unsigned fail=0;fail<2;++fail) {
   memset(&config,0,sizeof config);config.gnss_type=GNSS_TYPE_TAU804M;
   strcpy(config.terminal_model,"A300_406");strcpy(config.server_ip,"host");
   strcpy(config.pid,"12345678901");config.heartbeat_s=180;
   config.report_moving_s=30;config.report_stopped_s=180;
   config.vib_sens=30;config.gpsbds_mode=2;config.speed_limit_kmh=120;
   config.gmt_sign=1;config.gmt_hour=8;
   at_config_init();persist_ok=!fail;g_tick_ms=0;
   saves=system_resets=production_calls=ota_rechecks=0;
   server_calls=timer_calls=hb_calls=relay_calls=0;
   setter_port=0;setter_backup=false;setter_a=setter_b=0;setter_hb=0;setter_relay=false;
   memset(setter_ip,0,sizeof setter_ip);
   line(input);
   printf("%u|%u|%u|%u|%u|%u|%u|%u|%u|%u|%u|%u|%u|%s|",
    saves,system_resets,production_calls,ota_rechecks,server_calls,timer_calls,
    hb_calls,relay_calls,setter_port,setter_backup,setter_a,setter_b,setter_hb,setter_ip);
   printf("%u|",setter_relay);dump(&config,sizeof config);dump(console,console_len);putchar('\n');
  }
  ++cases;
 }
 fprintf(stderr,"cases=%u, persistence success/failure\n",cases);return 0;
}
'''
def main():
    commands=['VERSION','IMEI','CHECK','POSITION','SERVER','BSERVER','HEARTBEAT','TIMER','RELAY','REBOOT','ANGLEREP','AGPS','AGNSS','UNKNOWN','FACTORYCAP#','PARAM#']
    values=['','0','1','ON','on','OFF','off','INVALID','1,60','5,65535','65535,65535','65536,1','-1,60','+1,60','00001,60','host,9000','host,65535','host,65536','host,-1','net,user','net,user,extra','ON,30,2']
    corpus=[]
    for name in commands:
        for alias in (name,name.lower(),name.swapcase()):
            corpus += [alias,alias+'#']+[alias+'='+v for v in values]+[alias+','+v for v in values]
    data=('\n'.join(corpus)+'\n').encode();outputs=[];records=[]
    with tempfile.TemporaryDirectory(prefix='a300_console_diff_') as d:
        temp=Path(d)
        (temp/'n32l40x.h').write_text('#define GPIOA ((void*)0)\n#define GPIO_PIN_12 12U\n#define Bit_RESET 0\nint GPIO_ReadInputDataBit(void*,unsigned);\nvoid NVIC_SystemReset(void);\n')
        for tree in ('source-baseline','source-optimized'):
            a=m['load'](tree,'test_at_config_serial_f39.py');root=OUT/tree
            source=a.HARNESS.replace('int main(void)','int original_main(void)',1)
            globals='static unsigned server_calls,timer_calls,hb_calls,relay_calls;\nstatic uint16_t setter_port,setter_a,setter_b,setter_hb;\nstatic bool setter_backup,setter_relay;\nstatic char setter_ip[128];\n'
            source=source.replace('void jt808_set_heartbeat_s(uint16_t s) { (void)s; }',globals+'void jt808_set_heartbeat_s(uint16_t s) { ++hb_calls;setter_hb=s; }')
            source=source.replace('void jt808_set_report_interval(uint16_t a, uint16_t b) { (void)a; (void)b; }','void jt808_set_report_interval(uint16_t a,uint16_t b){++timer_calls;setter_a=a;setter_b=b;}')
            source=source.replace('void jt808_set_server(const char *ip, uint16_t p, bool b) { (void)ip; (void)p; (void)b; }','void jt808_set_server(const char *ip,uint16_t p,bool b){++server_calls;setter_port=p;setter_backup=b;strncpy(setter_ip,ip,sizeof setter_ip-1);}')
            source=source.replace('void relay_set(bool on) { (void)on; }','void relay_set(bool on){++relay_calls;setter_relay=on;}')
            h=temp/(tree+'.c');exe=temp/(tree+'.exe');h.write_text(source+EXTRA,encoding='utf-8')
            command=[a.compiler(),'-std=c99','-O2','-Wall','-Wextra','-Werror','-I',str(temp),'-I',str(root/'include'),str(h)]+[str(root/'src'/n) for n in ['at_config.c','f39_command.c','plate_encoding.c','f39_config_adapter.c','f39_reply.c','sms_command.c','terminal_identity.c']]+['-lm','-o',str(exe)]
            r=subprocess.run(command,capture_output=True);assert not r.returncode,r.stderr
            r=subprocess.run([str(exe)],input=data,capture_output=True);assert not r.returncode,r.stderr
            outputs.append(r.stdout);records.append({'tree':tree,'exit_code':r.returncode,'cases':len(corpus),'executions':2*len(corpus),'sha256':hashlib.sha256(r.stdout).hexdigest()})
    equal=outputs[0]==outputs[1]
    report={'equal':equal,'corpus_sha256':hashlib.sha256(data).hexdigest(),'results':records}
    (OUT/'evidence/differential-console.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2));assert equal

if __name__=='__main__': main()
