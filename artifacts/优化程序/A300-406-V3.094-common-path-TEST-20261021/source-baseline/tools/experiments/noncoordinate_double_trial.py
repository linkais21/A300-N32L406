"""DBL-01 isolated overlays; generated images are measurement inputs, not releases."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
CASES = ('baseline', 'altitude_float', 'altitude_exact', 'gps_float')


def altitude_function(source):
    start = source.index('static uint16_t altitude_extension_tail(')
    end = source.index('\n}', start) + 2
    return source[start:end]


EXACT = '''static uint16_t altitude_extension_tail(float altitude)
{
    /* IEEE binary32: |x| * 1000 = significand * 125 * 2^(exponent-147).
     * The 24-bit significand times 125 fits uint32_t. Shift only after
     * proving range; preserve floor, NaN/Inf and >=2^32 rejection exactly. */
    uint32_t bits, scaled, exponent, shift;
    memcpy(&bits, &altitude, sizeof(bits));
    exponent = (bits >> 23) & 255U;
    if (exponent == 255U) return 0U;
    if (exponent == 0U) return 0U; /* zero/subnormal: less than 1 mm */
    scaled = ((bits & 0x7fffffU) | 0x800000U) * 125U;
    if (exponent < 147U) {
        shift = 147U - exponent;
        scaled = shift >= 32U ? 0U : scaled >> shift;
    } else {
        shift = exponent - 147U;
        if (shift >= 32U || scaled > (UINT32_MAX >> shift)) return 0U;
        scaled <<= shift;
    }
    return (uint16_t)(scaled % 1000U);
}'''


def transform(source, case):
    if case not in CASES:
        raise ValueError(case)
    if case == 'baseline':
        return source
    if case.startswith('altitude_'):
        old = altitude_function(source)
        new = EXACT if case == 'altitude_exact' else old.replace(
            'double scaled = fabs((double)altitude) * 1000.0;',
            'float scaled = fabsf(altitude) * 1000.0f;').replace('4294967296.0', '4294967296.0f')
        return source.replace(old, new, 1)
    if case != 'gps_float':
        raise ValueError(case)
    start = source.index('static bool parse_decimal(')
    end = source.index('\n}', start) + 2
    parser = source[start:end].replace('parse_decimal', 'parse_decimal_float').replace('double', 'float')
    source = source[:end] + '\n\n' + parser + source[end:]
    source = source.replace('double lat, lon, hdop, altitude, geoid = 0.0;',
                            'double lat, lon; float hdop, altitude, geoid = 0.0f;')
    source = source.replace('double lat, lon, knots = 0.0, heading = 0.0;',
                            'double lat, lon; float knots = 0.0f, heading = 0.0f;')
    for field in ('hdop', 'altitude', 'geoid', 'knots', 'heading'):
        source, count = re.subn(r'parse_decimal\((f\[\d+\], &' + field + r')\)',
                                r'parse_decimal_float(\1)', source)
        if count != 1:
            raise ValueError('GPS field anchor changed: ' + field)
    return source.replace('knots * 1.852', 'knots * 1.852f')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=CASES, default=list(CASES))
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT/'build') or out == ROOT/'build':
        parser.error('output must be a new child of build/')
    out.mkdir(parents=True, exist_ok=False)
    make = ROOT.parent/'tools/w64devkit/w64devkit/bin/make.exe'
    # Native Windows recipes; do not allow an unrelated sh.exe to select POSIX recipes.
    env = os.environ.copy()
    env['PATH'] = os.pathsep.join(p for p in env['PATH'].split(os.pathsep)
                                if not (Path(p)/'sh.exe').exists())
    profile = subprocess.check_output([str(make), 'print-profile'], cwd=ROOT, env=env, text=True)
    sources = next(s.split('=', 1)[1].split() for s in profile.splitlines() if s.startswith('C_SRCS='))
    inputs = [p for folder in ('src', 'include', 'sdk', 'third_party', 'ldscript')
              for p in (ROOT/folder).rglob('*') if p.suffix in ('.c', '.h', '.s', '.ld')]
    inputs += [ROOT/'Makefile', ROOT/'release_identity.json', Path(__file__)]
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    (out/'input-hashes.json').write_text(json.dumps(hashes, indent=2))
    results = {}
    for case in args.cases:
        directory = out/case
        directory.mkdir()
        case_sources = list(sources)
        if case != 'baseline':
            name = 'src/gps.c' if case == 'gps_float' else 'src/jt808.c'
            target = directory/Path(name).name
            target.write_text(transform((ROOT/name).read_text(encoding='utf-8'), case), encoding='utf-8')
            case_sources[case_sources.index(name)] = target.relative_to(ROOT).as_posix()
        # Hold the existing identity fixed for all A/B builds. Normal `all`
        # refreshes three identity files, which invalidates a size comparison.
        common = [str(make), '-o', 'include/build_version.h', 'BUILD='+directory.relative_to(ROOT).as_posix(),
                  'C_SRCS='+' '.join(case_sources)]
        records = []
        for label, command in (
            ('build', common+['-j4', 'all']),
            ('gates', common+['-k', 'release-gate']),
            ('sections', [str(ROOT/'.toolchain/bin/arm-none-eabi-size.exe'), '-A', str(directory/'a300_firmware.elf')]),
            ('symbols', [str(ROOT/'.toolchain/bin/arm-none-eabi-nm.exe'), '-S', '--size-sort', str(directory/'a300_firmware.elf')]),
        ):
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=240)
            (directory/(label+'.log')).write_bytes(result.stdout+result.stderr)
            records.append(dict(command=command, exit_code=result.returncode, log=label+'.log'))
            if label == 'build' and result.returncode:
                raise RuntimeError('Build failed: '+str(directory/'build.log'))
        results[case] = dict(bin_bytes=(directory/'a300_firmware.bin').stat().st_size,
                             commands=records, release_approved=False)
        (out/'results.json').write_text(json.dumps(results, indent=2))
        print(case, results[case]['bin_bytes'], flush=True)
    changed = [p for p, digest in hashes.items() if hashlib.sha256((ROOT/p).read_bytes()).hexdigest() != digest]
    if changed:
        raise RuntimeError('Inputs changed during trial: '+str(changed))
    print('Production inputs unchanged; inspect gate logs before any further use.')


if __name__ == '__main__':
    main()
