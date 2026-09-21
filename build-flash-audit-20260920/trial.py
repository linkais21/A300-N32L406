from pathlib import Path
import hashlib, json, shutil, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(__file__).resolve().parent
make=shutil.which('mingw32-make.exe')
profile=subprocess.check_output([make,'print-profile'],cwd=ROOT,text=True)
sources=next(x.split('=',1)[1].split() for x in profile.splitlines() if x.startswith('C_SRCS='))
def candidate(name, changes):
    d=OUT/name; d.mkdir()
    src=list(sources)
    for filename, transform in changes.items():
        original=(ROOT/filename).read_text(encoding='utf-8')
        target=d/Path(filename).name
        target.write_text(transform(original),encoding='utf-8')
        src[src.index(filename)]=target.relative_to(ROOT).as_posix()
    command=[make,'-j4','size','flash-guard','BUILD='+d.relative_to(ROOT).as_posix(),'C_SRCS='+' '.join(src)]
    with (d/'build.log').open('w') as log:
        r=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    result={'command':command,'exit_code':r.returncode}
    if (d/'flash-capacity.json').exists(): result['capacity']=json.loads((d/'flash-capacity.json').read_text())
    (d/'result.json').write_text(json.dumps(result,indent=2))
    print(name,r.returncode,(d/'a300_firmware.bin').stat().st_size if (d/'a300_firmware.bin').exists() else 'failed',flush=True)
def share(s):
    for f in ('coordinate_extension_tail','clamp_voltage_units'):
        s=s.replace('static uint16_t '+f,'static __attribute__((noinline)) uint16_t '+f)
    return s
def ranges(s):
    old='''           isfinite(gps->lat) && isfinite(gps->lon) &&
           gps->lat >= -90.0 && gps->lat <= 90.0 &&
           gps->lon >= -180.0 && gps->lon <= 180.0 &&'''
    assert old in s
    return s.replace(old,'''           fabs(gps->lat) <= 90.0 && fabs(gps->lon) <= 180.0 &&''')
def gps_ranges(s):
    s=s.replace('#include <string.h>','#include <string.h>\n#include <math.h>')
    return s.replace('snapshot->lat < -90.0 || snapshot->lat > 90.0 ||','fabs(snapshot->lat) > 90.0 ||').replace('snapshot->lon < -180.0 || snapshot->lon > 180.0 ||','fabs(snapshot->lon) > 180.0 ||')
def mileage_ranges(s):
    return s.replace('g->lat >= -90.0 && g->lat <= 90.0 &&','fabs(g->lat) <= 90.0 &&').replace('g->lon >= -180.0 && g->lon <= 180.0','fabs(g->lon) <= 180.0')
def calendar(s):
    s=share(s)
    a=s.index('    static const uint8_t days_in_month[13]',s.index('bool jt808_location_snapshot_valid'))
    b=s.index('    if (gps == NULL',a)
    s=s[:a]+s[b:]
    a=s.index('    leap =',s.index('bool jt808_location_snapshot_valid'))
    b=s.index('\n}',a)
    s=s[:a]+'''    return gps->day >= 1U && gps->day <= jt808_days_in_month(gps->year, gps->month);'''+s[b:]
    s=s.replace('bool jt808_location_snapshot_valid(', 'static uint8_t jt808_days_in_month(uint16_t year, uint8_t month);\n\nbool jt808_location_snapshot_valid(',1)
    s=s.replace('static uint8_t jt808_days_in_month(uint16_t year, uint8_t month)\n{','static __attribute__((noinline)) uint8_t jt808_days_in_month(uint16_t year, uint8_t month)\n{')
    return s
if __name__=='__main__':
    name=sys.argv[1]
    cases={'share':{'src/jt808.c':share},'ranges':{'src/gps_report_filter.c':ranges},
           'combined':{'src/jt808.c':share,'src/gps_report_filter.c':ranges},
           'range_all':{'src/jt808.c':share,'src/gps_report_filter.c':ranges,'src/gps.c':gps_ranges,'src/mileage.c':mileage_ranges},
           'calendar':{'src/jt808.c':calendar,'src/gps_report_filter.c':ranges,'src/gps.c':gps_ranges,'src/mileage.c':mileage_ranges}}
    candidate(name,cases[name])
