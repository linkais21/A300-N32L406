"""Opt-in source overlays for size experiments; never edit production inputs."""
from pathlib import Path
import re
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]

# Exact call prefixes, reviewed as normal-path diagnostics. No broad log filter.
LOG_CALLS = {
    # EC800M receive/send lines are asserted by existing diagnostic contracts;
    # the first trial removed them and failed those tests. Keep them intact.
    'src/jt808.c': [
        '"[808] 0200 acc=%u alarm=0x%08lx hist=%u\\r\\n"',
        '"[808-RX] ch=%u msg=0x%04x sn=%u body=%u\\r\\n"',
        '"[808-RX] ch=%u bytes=%u\\r\\n"',
    ],
    'src/mileage.c': ['"[MILE] +%um total=%um\\r\\n"'],
}

def math_source(source, candidate='float'):
    if candidate not in ('float','bounded'): raise ValueError(candidate)
    start = source.index('static double haversine_m(')
    if 'static double mileage_trial_sin(' in source:
        start = source.index('static double mileage_trial_sin(')
    end = source.index('\nvoid mileage_update(void)',start)
    fragment = Path(__file__).with_name('mileage_distance_'+candidate+'.inc').read_text(encoding='utf-8')
    return source[:start] + fragment + '\n' + source[end:]

def log_source(source, name):
    if source.startswith('static inline int trial_discard_trace('):
        return source
    for literal in LOG_CALLS[name]:
        pattern = r'\bdbg_printf(?=\(\s*' + re.escape(literal) + ')'
        source, count = re.subn(pattern, 'trial_discard_trace', source)
        if count != 1:
            raise ValueError(f'{name}: expected one reviewed log call, got {count}: {literal}')
    # An empty variadic function preserves argument side effects, unlike a
    # no-op macro. At -Os/LTO the unused format literal/call can be eliminated.
    return ('static inline int trial_discard_trace(const char *fmt, ...)\n'
            '{ (void)fmt; return 0; }\n' + source)

def quantization_source(source):
    """Opt-in millimetre policy; preserve persistence and baseline scheduling."""
    if 'uint32_t dist_mm = (uint32_t)(dist_m * 1000.0 + 0.5);' in source:
        return source
    old = '    if (!g->valid) return;'
    new = '''    if (!g->valid ||
        !(g->lat >= -90.0 && g->lat <= 90.0 &&
          g->lon >= -180.0 && g->lon <= 180.0)) return;'''
    if source.count(old) != 1: raise ValueError('fix validation anchor changed')
    source = source.replace(old, new)
    start = source.index('    /* Stop-drift filter */', source.index('void mileage_update(void)'))
    end = source.index('\n    s_last_lat = g->lat;', start)
    return source[:start] + '''    /* Experimental policy: nearest millimetre, positive halfway up. */
    if (!isfinite(dist_m) || dist_m < 0.0) return;
    if (dist_m > 8192.0) dist_m = 8192.0;
    uint32_t dist_mm = (uint32_t)(dist_m * 1000.0 + 0.5);
    uint32_t threshold_mm = (uint32_t)c->stopdrift_thr * 100U;
    if (c->stopdrift_en && g->speed_kmh < 2.0f && dist_mm < threshold_mm)
        return;
    if (dist_mm > 500U && dist_mm < 1000000U) {
        uint32_t delta_m = dist_mm / 1000U;
        cfg_add_mileage(delta_m);
        dbg_printf("[MILE] +%um total=%um\\r\\n",
                   (unsigned)delta_m, (unsigned)c->mileage_m);
    }
''' + source[end:]

def run(command, cwd, log):
    result = subprocess.run([str(x) for x in command],cwd=cwd,capture_output=True,
                            text=True,encoding='utf-8',errors='replace',timeout=240)
    log.write_text(result.stdout+result.stderr,encoding='utf-8')
    return {'command':[str(x) for x in command], 'exit_code':result.returncode,
            'log':log.name}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='new directory under repository build/')
    parser.add_argument('--math',choices=['float','bounded'],default='float')
    parser.add_argument('--quantize-mm',action='store_true',help='apply experimental mm policy to math cases only')
    parser.add_argument('--cases',nargs='+',choices=['baseline','math','logs','combined'],default=['baseline','math','logs','combined'])
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT/'build') or out == ROOT/'build':
        parser.error('output must be a new child of the repository build directory')
    out.mkdir(parents=True,exist_ok=False)
    make = Path(os.environ.get('A300_MAKE',ROOT.parent/'tools/w64devkit/w64devkit/bin/make.exe'))
    files = [p for folder in ['src','include','sdk','third_party','ldscript']
             for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ['.c','.h','.s','.ld']]
    files += [ROOT/'Makefile',ROOT/'release_identity.json',Path(__file__),Path(__file__).with_name('mileage_distance_'+args.math+'.inc')]
    hashes = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (out/'input-hashes.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    profile = subprocess.check_output([str(make),'print-profile'],cwd=ROOT,text=True)
    sources = next(line.split('=',1)[1].split() for line in profile.splitlines() if line.startswith('C_SRCS='))
    (out/'log-calls.json').write_text(json.dumps(LOG_CALLS,indent=2),encoding='utf-8')
    results = {}
    for name, math, logs in [('baseline',False,False),('math',True,False),('logs',False,True),('combined',True,True)]:
        if name not in args.cases: continue
        case = out/name
        case.mkdir()
        case_sources = list(sources)
        for source_name in sorted(set(LOG_CALLS) if logs else ({'src/mileage.c'} if math else set())):
            original = (ROOT/source_name).read_text(encoding='utf-8')
            generated = math_source(original,args.math) if math and source_name=='src/mileage.c' else original
            if args.quantize_mm and math and source_name=='src/mileage.c':
                generated = quantization_source(generated)
            if logs: generated = log_source(generated,source_name)
            target = case/'sources'/Path(source_name).name
            target.parent.mkdir(exist_ok=True)
            target.write_text(generated,encoding='utf-8')
            case_sources[case_sources.index(source_name)] = target.relative_to(ROOT).as_posix()
        common = [str(make),'BUILD='+case.relative_to(ROOT).as_posix(),'C_SRCS='+' '.join(case_sources)]
        commands = [run(common+['-j4','all'],ROOT,case/'build.log')]
        if commands[0]['exit_code']:
            raise RuntimeError(f'{name} build failed; see {case}/build.log')
        if re.search(r'warning:',(case/'build.log').read_text(encoding='utf-8'),re.I):
            raise RuntimeError(f'{name} compiler warning; see {case}/build.log')
        commands.append(run(common+['-k','release-gate'],ROOT,case/'release-gate.log'))
        commands.append(run([sys.executable,'tools/libc_parser_guard.py',case/'a300_firmware.map'],ROOT,case/'libc.log'))
        commands.append(run([sys.executable,'tools/tests/test_ram01_frame_budget.py',case],ROOT,case/'frame-budget.log'))
        commands.append(run([ROOT/'.toolchain/bin/arm-none-eabi-size.exe','-A',case/'a300_firmware.elf'],ROOT,case/'sections.log'))
        commands.append(run([ROOT/'.toolchain/bin/arm-none-eabi-nm.exe','-S','--size-sort',case/'a300_firmware.elf'],ROOT,case/'symbols.log'))
        cap = json.loads((case/'flash-capacity.json').read_text())
        stack = json.loads((case/'stack-analysis.json').read_text())
        results[name] = dict(files={ext:(case/f'a300_firmware.{ext}').stat().st_size for ext in ['elf','hex','bin']},
                             math_candidate=args.math if math else None,
                             quantize_mm=args.quantize_mm and math,
                             remaining=cap['remaining_bytes'],known_call_frames=stack['known_main_frame_sum'],commands=commands,
                             release_approved=False)
        (out/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
        print(name,results[name]['files'],'remaining',cap['remaining_bytes'],flush=True)
    changed=[p for p,h in hashes.items() if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h]
    if changed: raise RuntimeError(f'inputs changed during experiment: {changed}')
    print('Production inputs unchanged. Experimental images only; inspect failed gates before any HIL use.')

if __name__ == '__main__': main()
