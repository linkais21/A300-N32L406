"""Assess a proposed 1 mm decision rule using the saved real-C distance replay."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import struct
import subprocess

from firmware_size_trial import ROOT, math_source
from replay_mileage_size_trial import destination

def decision(distance, values):
    lat1,lon1,lat2,lon2,speed,enabled,raw,valid=values
    if not valid: return (0,0,0)
    if (lat1,lon1)==(lat2,lon2): return (0,0,1)
    if not math.isfinite(distance) or distance<0: return None
    mm=int(math.floor(min(distance,8192.0)*1000.0+0.5))
    speed=struct.unpack('f',struct.pack('f',speed))[0]
    if enabled and speed<2 and mm<int(raw)*100: return (0,0,0)
    accumulate=500<mm<1000000
    return (mm//1000 if accumulate else 0,int(accumulate),1)

def compare(inputs,outputs):
    differences=[];legacy_changes=[];invalid=[]
    for index,values in enumerate(inputs):
        a,b=outputs['baseline'][index],outputs['math'][index]
        pa,pb=decision(float(a[0]),values),decision(float(b[0]),values)
        if pa is None or pb is None:
            invalid.append(index);continue
        if pa!=pb:
            differences.append(dict(index=index,input=values,baseline_distance=float(a[0]),
                                    candidate_distance=float(b[0]),baseline_quantized=pa,candidate_quantized=pb))
        if (int(a[1]),int(a[3]),int(a[5]))!=pb: legacy_changes.append(index)
    return dict(samples=len(inputs),quantized_algorithm_differences=len(differences),
                changed_from_legacy=len(legacy_changes),invalid_distance_indices=invalid,
                differences=differences,legacy_change_indices=legacy_changes)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();replay=args.replay.resolve();out=args.output.resolve()
    if not replay.is_relative_to(ROOT/'build') or not out.is_relative_to(ROOT/'build'):
        parser.error('replay and output must be under build/')
    source=(ROOT/'src/mileage.c').read_text(encoding='utf-8')
    assert (replay/'baseline/mileage_under_test.c').read_text(encoding='utf-8')==source
    assert (replay/'math/mileage_under_test.c').read_text(encoding='utf-8')==math_source(source,'bounded')
    out.mkdir(parents=True,exist_ok=False)
    inputs=[list(map(float,line.split())) for line in (replay/'synthetic-inputs.txt').read_text().splitlines()]
    outputs={name:[line.split() for line in (replay/name/'output.txt').read_text().splitlines()] for name in ['baseline','math']}
    report={'existing_replay':compare(inputs,outputs),'production_changed':False,'policy_approved':False,
            'method':'real C distance executables, proposed policy evaluated in Python; not firmware validation'}
    # Move the adversarial points to the NEW rounding discontinuities instead
    # of testing only the old integer/threshold boundaries.
    shifted=[]
    for lat in [-85,-45,0,23,60,85]:
        for bearing in [0,90,180]:
            for threshold in [0.5,1,2,5,999,1000,6553.5]:
                for eps in [-1e-8,0,1e-8]:
                    lat2,lon2=destination(lat,179.999999,threshold-0.0005+eps,bearing)
                    for enabled in [0,1]:
                        shifted.append([lat,179.999999,lat2,lon2,0,enabled,min(65535,int(threshold*10)),1])
    wire=''.join(' '.join(map(str,row))+'\n' for row in shifted)
    (out/'half-mm-inputs.txt').write_text(wire,encoding='ascii')
    shifted_outputs={};exe_hashes={}
    for name in ['baseline','math']:
        exe=replay/name/'replay.exe'
        exe_hashes[name]=hashlib.sha256(exe.read_bytes()).hexdigest()
        run=subprocess.run([str(exe)],input=wire,capture_output=True,text=True,check=True,timeout=30)
        (out/(name+'-half-mm-output.txt')).write_text(run.stdout,encoding='ascii')
        shifted_outputs[name]=[line.split() for line in run.stdout.splitlines()]
        assert len(shifted_outputs[name])==len(shifted)
    report['half_mm_replay']=compare(shifted,shifted_outputs)
    report['executable_sha256']=exe_hashes
    (out/'assessment.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    for name in ['existing_replay','half_mm_replay']:
        print(name,json.dumps({k:v for k,v in report[name].items() if k not in ['differences','legacy_change_indices']}))

if __name__=='__main__':main()
