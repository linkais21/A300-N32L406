"""Compare real production mileage_update against a generated math overlay.

Only synthetic coordinates are used. Host libm results do not certify ARM libm.
Decision differences are reported, never rounded away to claim equivalence.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import math
import random
import shutil
import subprocess

from firmware_size_trial import ROOT, math_source, quantization_source

SPEC = importlib.util.spec_from_file_location('persistence', ROOT/'tools/tests/test_mileage_persistence.py')
persist = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(persist)

HARNESS = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "gps.h"
#include "flash_config.h"
static gps_data_t gps;
static device_config_t config;
static unsigned added_calls;
const gps_data_t *gps_get_data(void) { return &gps; }
device_config_t *cfg_get(void) { return &config; }
void cfg_add_mileage(uint32_t delta) { config.mileage_m+=delta; ++added_calls; }
bool cfg_mileage_dirty(void) { return false; }
uint32_t cfg_persist_generation(void) { return 0; }
bool cfg_flush_mileage(void) { return true; }
uint32_t test_tick_ms(void) { return 0; }
int dbg_printf(const char *fmt, ...) { (void)fmt; return 0; }
#include "mileage_under_test.c"
int main(void) {
    double lat1,lon1,lat2,lon2;
    float speed;
    unsigned enable,threshold,valid;
    while (scanf("%lf %lf %lf %lf %f %u %u %u",&lat1,&lon1,&lat2,&lon2,
                 &speed,&enable,&threshold,&valid)==8) {
        s_has_first=false; s_last_lat=s_last_lon=0;
        memset(&config,0,sizeof config); memset(&gps,0,sizeof gps);
        added_calls=0;
        config.stopdrift_en=(uint8_t)enable; config.stopdrift_thr=(uint16_t)threshold;
        gps.valid=true; gps.lat=lat1; gps.lon=lon1; gps.speed_kmh=speed;
        mileage_update();
        double d=haversine_m(lat1,lon1,lat2,lon2);
        gps.valid=valid!=0; gps.lat=lat2; gps.lon=lon2;
        mileage_update();
        unsigned once=config.mileage_m, calls=added_calls;
        mileage_update(); mileage_update();
        printf("%.17g %u %u %u %u %d\n",d,once,config.mileage_m,calls,added_calls,
               s_last_lat==lat2 && s_last_lon==lon2);
    }
    return ferror(stdin) ? 2 : 0;
}
'''

ROUTE_HARNESS = HARNESS.split('int main(void)',1)[0]+r'''
int main(void) {
    double lat,lon;
    float speed;
    unsigned reset,valid,enable,threshold;
    while (scanf("%u %lf %lf %f %u %u %u",&reset,&lat,&lon,&speed,&valid,&enable,&threshold)==7) {
        if (reset) { s_has_first=false; s_last_lat=s_last_lon=0; config.mileage_m=0; }
        config.stopdrift_en=(uint8_t)enable; config.stopdrift_thr=(uint16_t)threshold;
        gps.lat=lat; gps.lon=lon; gps.speed_kmh=speed; gps.valid=valid!=0;
        mileage_update();
        printf("%u %.17g %.17g\n",config.mileage_m,s_last_lat,s_last_lon);
    }
    return 0;
}
'''

def destination(lat,lon,metres,bearing):
    phi=math.radians(lat); lam=math.radians(lon); theta=math.radians(bearing); arc=metres/6371000.0
    p=math.asin(max(-1.0,min(1.0,math.sin(phi)*math.cos(arc)+math.cos(phi)*math.sin(arc)*math.cos(theta))))
    l=lam+math.atan2(math.sin(theta)*math.sin(arc)*math.cos(phi),math.cos(arc)-math.sin(phi)*math.sin(p))
    return math.degrees(p),(math.degrees(l)+180)%360-180

def cases():
    rng=random.Random(3051)
    result=[]
    def add(kind,lat,lon,lat2,lon2,speed=20.0,enable=0,threshold=50,valid=1):
        result.append((kind,(lat,lon,lat2,lon2,speed,enable,threshold,valid)))
    for i in range(16000):
        lat=rng.uniform(-89.9,89.9); lon=rng.uniform(-180,180)
        distance=10**rng.uniform(-3,4); lat2,lon2=destination(lat,lon,distance,rng.uniform(0,360))
        add('local',lat,lon,lat2,lon2,speed=rng.choice([0,1.99,2,20]),enable=i%2,threshold=rng.choice([1,5,50,100,10000,65535]))
    for i in range(4000):
        add('global',rng.uniform(-90,90),rng.uniform(-180,180),rng.uniform(-90,90),rng.uniform(-180,180),enable=i%2,threshold=65535)
    # Deliberately sit on business/quantization boundaries. Failures here are
    # important even when the distance error is much smaller than one cm.
    for lat in [-89.9999,-85,-45,0,23,60,85,89.9999]:
        for bearing in [0,90,180,270]:
            for distance in [0.5,1,2,5,10,50,100,999,1000,1000.1,6553.5]:
                for offset in [-0.02,-0.001,-0.00001,0,0.00001,0.001,0.02]:
                    lat2,lon2=destination(lat,179.999999,distance+offset,bearing)
                    for enable in [0,1]:
                        add('boundary',lat,179.999999,lat2,lon2,speed=0,enable=enable,threshold=min(65535,int(distance*10)))
    for lat in [-90,-89.999999,0,89.999999,90]:
        for lon in [-180,-179.999999,0,179.999999,180]:
            for lat2,lon2 in [(lat,lon),(lat,-lon),(-lat,(lon+180)%360-180),(0,0)]:
                add('extreme',lat,lon,lat2,lon2)
                add('invalid_fix',lat,lon,lat2,lon2,valid=0)
    return result

def route_cases():
    rng=random.Random(3052); rows=[]
    for lat,lon in [(-89,0),(-60,20),(0,179.9999),(23,114),(60,-179.9999),(89,100)]:
        for index in range(2000):
            if index and index%9:
                lat,lon=destination(lat,lon,2000 if index%701==0 else rng.uniform(0.05,80),rng.uniform(0,360))
            rows.append((int(index==0),lat,lon,rng.choice([0,1.99,2,30]),int(index%111!=0),int(index%5!=0),rng.choice([5,50,100])))
    return rows

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--math',choices=['float','bounded'],default='float')
    parser.add_argument('--quantize-mm',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'build'): parser.error('output must be under repository build/')
    out.mkdir(parents=True,exist_ok=False)
    cc=shutil.which('gcc')
    if cc is None: raise RuntimeError('host GCC required')
    original=(ROOT/'src/mileage.c').read_text(encoding='utf-8')
    dataset=cases();wire=''.join(' '.join(str(x) for x in values)+'\n' for _,values in dataset)
    (out/'synthetic-inputs.txt').write_text(wire,encoding='ascii')
    route=route_cases();route_wire=''.join(' '.join(str(x) for x in row)+'\n' for row in route)
    (out/'synthetic-route.txt').write_text(route_wire,encoding='ascii')
    outputs={};route_outputs={};commands=[]
    candidate=math_source(original,args.math)
    if args.quantize_mm: candidate=quantization_source(candidate)
    for name,source in [('baseline',original),('math',candidate)]:
        folder=out/name;folder.mkdir()
        for header,content in persist.HEADERS.items(): (folder/header).write_text(content,encoding='ascii')
        (folder/'mileage_under_test.c').write_text(source,encoding='utf-8')
        (folder/'replay.c').write_text(HARNESS,encoding='ascii')
        command=[cc,'-std=c99','-Os','-Wall','-Wextra','-Werror','-I',str(folder),str(folder/'replay.c'),'-lm','-o',str(folder/'replay.exe')]
        subprocess.run(command,check=True,capture_output=True);commands.append(command)
        run=subprocess.run([str(folder/'replay.exe')],input=wire,capture_output=True,text=True,check=True)
        (folder/'output.txt').write_text(run.stdout,encoding='ascii')
        rows=[line.split() for line in run.stdout.splitlines()]
        assert len(rows)==len(dataset)
        outputs[name]=[(float(row[0]),tuple(int(x) for x in row[1:])) for row in rows]
        # Reuse the existing real-C persistence scheduler regression on each.
        (folder/'persist.c').write_text(persist.HARNESS,encoding='ascii')
        command=[cc,'-std=c99','-Os','-Wall','-Wextra','-Werror','-I',str(folder),'-I',str(ROOT/'include'),str(folder/'persist.c'),str(folder/'mileage_under_test.c'),'-lm','-o',str(folder/'persist.exe')]
        subprocess.run(command,check=True,capture_output=True);commands.append(command)
        run=subprocess.run([str(folder/'persist.exe')],capture_output=True,text=True,check=True)
        (folder/'persistence.log').write_text(run.stdout,encoding='utf-8')
        (folder/'route.c').write_text(ROUTE_HARNESS,encoding='ascii')
        command=[cc,'-std=c99','-Os','-Wall','-Wextra','-Werror','-I',str(folder),str(folder/'route.c'),'-lm','-o',str(folder/'route.exe')]
        subprocess.run(command,check=True,capture_output=True);commands.append(command)
        run=subprocess.run([str(folder/'route.exe')],input=route_wire,capture_output=True,text=True,check=True)
        (folder/'route-output.txt').write_text(run.stdout,encoding='ascii')
        route_outputs[name]=[line.split() for line in run.stdout.splitlines()]
        assert len(route_outputs[name])==len(route)
    local_errors=[];policy_errors=[];decision_diffs=[];outside_tolerance=[];nonfinite=[]
    count_diffs=base_diffs=integer_diffs=0
    for index,((kind,values),(d0,s0),(d1,s1)) in enumerate(zip(dataset,outputs['baseline'],outputs['math'])):
        if math.isfinite(d0) and math.isfinite(d1):
            error=abs(d0-d1)
            if d0<=6553.5: policy_errors.append(error)
            if d0<=1000:
                local_errors.append(error)
                if error>0.01: outside_tolerance.append(index)
        else: nonfinite.append(dict(index=index,kind=kind,baseline=str(d0),candidate=str(d1)))
        assert s0[0]==s0[1] and s1[0]==s1[1], 'repeated fix adds mileage twice'
        if s0!=s1:
            integer_diffs+=s0[0]!=s1[0]
            count_diffs+=s0[2]!=s1[2]
            base_diffs+=s0[4]!=s1[4]
            decision_diffs.append(dict(index=index,kind=kind,input=values,distance_before=d0,distance_after=d1,
                                       state_before=s0,state_after=s1))
    local_errors.sort()
    from collections import Counter
    route_diffs=[i for i,(a,b) in enumerate(zip(route_outputs['baseline'],route_outputs['math'])) if a!=b]
    report=dict(math_candidate=args.math,quantize_mm=args.quantize_mm,samples=len(dataset),local_samples=len(local_errors),local_limit_m=0.01,
                max_local_error_m=max(local_errors),p99_local_error_m=local_errors[int(len(local_errors)*0.99)],
                max_stopdrift_range_error_m=max(policy_errors),
                outside_local_tolerance=outside_tolerance,nonfinite=nonfinite,
                decision_difference_count=len(decision_diffs),integer_mileage_differences=integer_diffs,
                accumulation_branch_differences=count_diffs,baseline_advance_differences=base_diffs,
                differences_by_group=dict(Counter(r['kind'] for r in decision_diffs)),
                route_samples=len(route),route_differing_rows=len(route_diffs),
                route_segment_end_mileage=[{'baseline':int(route_outputs['baseline'][i][0]),'candidate':int(route_outputs['math'][i][0])} for i in range(1999,len(route),2000)],
                behavior_equivalent=not decision_diffs,host_only=True,release_approved=False,
                baseline_integer_sum=sum(row[1][0] for row in outputs['baseline']),
                candidate_integer_sum=sum(row[1][0] for row in outputs['math']),commands=commands)
    (out/'replay-summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (out/'decision-differences.json').write_text(json.dumps(decision_diffs,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['commands','nonfinite','outside_local_tolerance']},indent=2))
    if outside_tolerance: raise SystemExit('Candidate failed local accuracy screen; see report')

if __name__=='__main__': main()
