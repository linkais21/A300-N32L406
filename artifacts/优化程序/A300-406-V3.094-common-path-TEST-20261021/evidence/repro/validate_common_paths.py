"""Differential replay of the actual baseline and optimized C command paths."""
from pathlib import Path
import runpy, importlib.util, subprocess, tempfile, hashlib, json, random

OUT=Path(__file__).resolve().parents[2]

def load(tree,name):
    p=OUT/tree/'tools/tests'/name
    spec=importlib.util.spec_from_file_location(name,p)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod

EXTRA=r'''
#include <stdio.h>
static void dump(const void *v,size_t n) {
 const unsigned char *p=v;
 for(size_t i=0;i<n;++i) printf("%02x",p[i]);
 putchar('|');
}
int main(void) {
 char text[256]; unsigned cases=0;
 assert(original_main()==0);
 while(fgets(text,sizeof text,stdin)) {
  size_t len=strcspn(text,"\n"); text[len]=0;
  for(unsigned failure=0;failure<2;++failure) {
   device_config_t cfg=seed();spy_t s={0};f39_reply_t reply={0};
   f39_request_t req;f39_platform_t p=platform(&cfg,&s);
   p.fota_recheck=recheck_ota;s.persist_ok=!failure;s.gps_ok=true;s.speed=0;
   f39_result_t status=f39_parse((const uint8_t*)text,(uint16_t)len,&req);
   if(status==F39_RESULT_OK) status=f39_execute(&req,&p,&reply);
   printf("%u|%u|%u|%u|%u|%u|%u|%u|%u|%u|%u|%u|%u|%u|%s|",
       status,reply.len,reply.reset_pending,reply.reset_delay_ms,
       s.saves,s.reconnects,s.auth_resets,s.auth_reset_mask,s.pdp_restarts,
       s.timers,s.gnss,s.relays,s.relay,ota_rechecks,s.order);
   dump(&cfg,sizeof cfg);dump(reply.data,reply.len);putchar('\n');
  }
  ++cases;
 }
 fprintf(stderr,"cases=%u, including persistence success/failure\n",cases);
 return 0;
}
'''

def main():
    rng=random.Random(300406)
    ops=['PID','IP','FIP','FREQ','HBT','MODEL','SPEED','APN','RELAY','GPSDUP','MLG','CAR','GPSBDS','GMTSET','VIBSENS','FKEY','FOTA','LOG','PARAM','RESET']
    values=['','0','1','2','3','19','20','29','30','50','51','60','200','201','300','3600','3601','65535','65536','42949672','42949673','4294967295','4294967296','00001','+1','-1',' 1','1 ','1x','0,0','1,60','5,65535','host,1','host,65535','host,65536','AUTO','net,,','net,user,password','E,8,0','W,12,59','0'*180,'9'*180,'x'*31,'x'*32,'x'*63,'x'*64]
    corpus=[op for op in ops]+[op+','+v for op in ops for v in values]
    corpus += ['DUALSET,'+a+'*'+b for a in ['HBT,30','IP,host,1','APN,net,,','MODEL,X','GPSBDS,1','FREQ,5,60','FKEY,1234567890ABCDEF','MLG,42949672'] for b in ['HBT,3600','SPEED,20','IP,host,65535','APN,AUTO','GPSDUP,0','VIBSENS,50','MODEL,Y','CAR,ABC']]
    seeds=corpus[:]
    for _ in range(5000):
        s=rng.choice(seeds);at=rng.randrange(len(s)+1)
        corpus.append(s[:at]+rng.choice([',','*','#','?','0','9',' ','"','\\'])+s[at:])
    corpus += [op+','+('x'*n) for op in ops for n in (0,1,30,31,32,63,64,127,180,190,191,192)]
    data=('\n'.join(corpus)+'\n').encode('ascii')
    results=[];outputs=[]
    with tempfile.TemporaryDirectory(prefix='a300_equivalence_') as d:
        tmp=Path(d)
        for tree in ('source-baseline','source-optimized'):
            a=load(tree,'test_f39_actions.py');root=OUT/tree
            h=tmp/(tree+'.c');exe=tmp/(tree+'.exe')
            h.write_text(a.HARNESS.replace('int main(void)','int original_main(void)',1)+EXTRA,encoding='utf-8')
            command=[a.find_compiler(),'-std=c99','-O2','-Wall','-Wextra','-Werror','-ffunction-sections','-I',str(root/'include'),str(h)]+[str(root/'src'/n) for n in ['plate_encoding.c','f39_command.c','f39_config_adapter.c','f39_reply.c','terminal_identity.c']]+['-Wl,--gc-sections','-o',str(exe)]
            build=subprocess.run(command,capture_output=True);assert build.returncode==0,build.stderr
            run=subprocess.run([str(exe)],input=data,capture_output=True);assert run.returncode==0,run.stderr
            outputs.append(run.stdout)
            results.append({'tree':tree,'exit_code':run.returncode,'command':command,'cases':len(corpus),'executions':2*len(corpus),'stdout_sha256':hashlib.sha256(run.stdout).hexdigest(),'stderr':run.stderr.decode()})
    equal=outputs[0]==outputs[1]
    if not equal:
        a,b=outputs[0].splitlines(),outputs[1].splitlines()
        first=next(i for i,(x,y) in enumerate(zip(a,b)) if x!=y)
        results.append({'first_difference_command':corpus[first//2],'persistence_failure':first%2})
    report={'equal':equal,'corpus_sha256':hashlib.sha256(data).hexdigest(),'results':results}
    (OUT/'evidence/differential-f39.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2));assert equal

if __name__=='__main__':main()
