"""Replay real GGA/RMC C functions; retain decision differences, never relax them."""
import argparse
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile

import noncoordinate_double_trial as trial
sys.path.insert(0, str(trial.ROOT/'tools/tests'))
from test_f39_actions import find_compiler

MAIN = r'''
int main(void) {
 char line[512];
 (void)nmea_checksum_ok;
 while(fgets(line,sizeof(line),stdin)) {
   line[strcspn(line,"\r\n")]=0; memset(&s_gps,0,sizeof(s_gps));
   int rc = line[0]=='G' ? parse_gga(line) : parse_rmc(line);
   unsigned speed=s_gps.speed_kmh<=0?0:s_gps.speed_kmh>=6553.5f?65535:(unsigned)(s_gps.speed_kmh*10.0f);
   printf("%d %.17g %.17g %.9g %.9g %.9g %.9g %.9g %u %d %d\n",rc,
          s_gps.lat,s_gps.lon,s_gps.speed_kmh,s_gps.heading,s_gps.altitude_m,
          s_gps.geoid_sep_m,s_gps.hdop,speed,s_gps.speed_kmh<2.0f,s_gps.speed_kmh>60.0f);
 }
 return 0;
}
'''


def sentences():
    # All coordinates synthetic. Five scalar fields tested with identical lexemes.
    values = ['', '0', '-0', '+0', '1.', '.', '1e2', 'nan', 'inf', '1x',
              '4294967295', '4294967296', '0.000000001', '0.0000000001',
              '359.999999999', '360', '-0.000000001', '6553.5']
    rng = random.Random(0xDB101)
    values += [f'{rng.randrange(-1000,10000)}.{rng.randrange(1000000000):09d}' for _ in range(3000)]
    for kmh in (0.5, 2, 3, 5, 30, 60, 120, 6553.5):
        centre = round(kmh/1.852*1e9)
        values += [f'{(centre+i)/1e9:.9f}' for i in range(-32,33)]
    for value in values:
        yield f'GPGGA,123520,1000.000,N,02000.000,E,1,08,{value},12.345,M,1.2,M,,'
        yield f'GPGGA,123520,1000.000,N,02000.000,E,1,08,0.9,{value},M,1.2,M,,'
        yield f'GPGGA,123520,1000.000,N,02000.000,E,1,08,0.9,12.345,M,{value},M,,'
        yield f'RMC,123520,A,1000.000,N,02000.000,E,{value},12.3,180926,,'
        yield f'RMC,123520,A,1000.000,N,02000.000,E,2.0,{value},180926,,'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(trial.ROOT/'build') or out == trial.ROOT/'build':
        parser.error('output must be a new child of build/')
    out.mkdir(parents=True, exist_ok=False)
    original = (trial.ROOT/'src/gps.c').read_text(encoding='utf-8')
    lines = list(sentences())
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        for case in ('baseline', 'gps_float'):
            source = trial.transform(original, case)
            # Real parser bodies, with hardware/ISR/transport outside this numeric experiment.
            fragment = source[source.index('static uint8_t nmea_split('):source.index('static void parse_gsv(')]
            harness = '#include <stdio.h>\n#include <string.h>\n#include "gps.h"\n'
            harness += '#define NMEA_FIELD_MAX 24\n#define TICK_MS() 1000U\n'
            harness += 'static gps_data_t s_gps; static uint32_t s_gga_ms;\n'
            harness += 'typedef enum {NMEA_PARSE_OK,NMEA_PARSE_FORMAT,NMEA_PARSE_NO_FIX} nmea_parse_result_t;\n'
            (p/'replay.c').write_text(harness+fragment+MAIN, encoding='utf-8')
            command = [find_compiler(), '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                       '-I', str(trial.ROOT/'include'), str(p/'replay.c'), '-o', str(p/'replay.exe')]
            subprocess.run(command, check=True)
            result = subprocess.run([str(p/'replay.exe')], input='\n'.join(lines)+'\n',
                                    text=True, capture_output=True, check=True, timeout=60)
            (out/(case+'.txt')).write_text(result.stdout)
            results.append(result.stdout.splitlines())
    assert len(results[0]) == len(results[1]) == len(lines)
    counts = dict(samples=len(lines), acceptance=0, scalar=0, speed_wire=0, speed_lt_2=0, speed_gt_60=0)
    differences = []
    for sentence, old, new in zip(lines, *results):
        a, b = old.split(), new.split()
        counts['acceptance'] += a[0] != b[0]
        if a[0] == b[0] == '0':
            assert a[1:3] == b[1:3], 'coordinate contract changed'
            counts['scalar'] += a[3:8] != b[3:8]
            for key, index in (('speed_wire',8), ('speed_lt_2',9), ('speed_gt_60',10)):
                counts[key] += a[index] != b[index]
        if old != new:
            differences.append(dict(sentence=sentence, baseline=old, candidate=new))
    summary = dict(counts, behavior_equivalent=not differences, release_approved=False)
    (out/'results.json').write_text(json.dumps(summary, indent=2))
    (out/'decision-differences.json').write_text(json.dumps(differences, indent=2))
    (out/'input-gps.c').write_text(original, encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
