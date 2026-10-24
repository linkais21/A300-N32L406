"""Acceptance checks for isolated size overlays; no production profile changes."""
import importlib.util
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
import math

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('size_trial', ROOT/'tools/experiments/firmware_size_trial.py')
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)

class TrialTests(unittest.TestCase):
    def test_log_overlay_emits_no_trace_and_preserves_argument_evaluation(self):
        source = r'''
#include <stdio.h>
int main(void) {
    unsigned calls=0;
    dbg_printf("[808] 0200 acc=%u alarm=0x%08lx hist=%u\r\n", ++calls, 0UL, 0U);
    dbg_printf("[808-RX] ch=%u msg=0x%04x sn=%u body=%u\r\n", ++calls, 3U, 1U, 5U);
    dbg_printf("[808-RX] ch=%u bytes=%u\r\n", ++calls, 4U);
    dbg_printf("[808-RX] ch=0 drop=CHECKSUM\r\n");
    dbg_printf("[808] ch0 ONLINE\r\n");
    return calls==3 ? 0 : 1;
}
'''
        candidate = trial.log_source(source, 'src/jt808.c')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p/'probe.c').write_text('#define dbg_printf printf\n'+candidate)
            subprocess.run([shutil.which('gcc'),'-std=c99','-Wall','-Wextra','-Werror',str(p/'probe.c'),'-o',str(p/'probe.exe')],check=True,capture_output=True)
            run = subprocess.run([str(p/'probe.exe')],check=True,capture_output=True,text=True)
            self.assertEqual([s for s in run.stdout.splitlines() if s],['[808-RX] ch=0 drop=CHECKSUM','[808] ch0 ONLINE'])

    def test_math_candidate_leaves_state_machine_and_persistence_unchanged(self):
        source = (ROOT/'src/mileage.c').read_text(encoding='utf-8')
        for name in ['float','bounded']:
            candidate = trial.math_source(source,name)
            self.assertEqual(candidate.split('void mileage_update(void)',1)[1],source.split('void mileage_update(void)',1)[1])
            if name == 'float':
                self.assertTrue(candidate!=source, 'float experiment must replace the integrated bounded function')

    def test_log_change_is_limited_to_reviewed_call_names(self):
        for name,literals in trial.LOG_CALLS.items():
            source=(ROOT/name).read_text(encoding='utf-8')
            # The reviewed log suppression is now integrated. Reconstruct the
            # unsuppressed input to keep testing the generator's narrow scope.
            if source.startswith('static inline int trial_discard_trace('):
                source=source.split('{ (void)fmt; return 0; }\n',1)[1]
            source=(source.replace('trial_discard_trace','dbg_printf')
                    .replace('dbg_printf_verbose','dbg_printf')
                    .replace('DBG_PRINTF_VERBOSE','dbg_printf'))
            candidate=trial.log_source(source,name)
            body=candidate.split('{ (void)fmt; return 0; }\n',1)[1]
            self.assertEqual(body.replace('trial_discard_trace','dbg_printf'),source)
            self.assertEqual(body.count('trial_discard_trace('),len(literals))
        self.assertNotIn('src/ec800m.c',trial.LOG_CALLS)
        for token in ['"[808-RX] ch=%u drop=CHECKSUM', '"[MILE] persist failed', '"[808] ch%u ONLINE']:
            self.assertTrue(any(token in trial.log_source((ROOT/name).read_text(encoding='utf-8'),name) for name in trial.LOG_CALLS))

    def test_bounded_distance_geographic_edges_and_large_distance_policy(self):
        fragment=(ROOT/'tools/experiments/mileage_distance_bounded.inc').read_text(encoding='utf-8')
        harness='#include <math.h>\n#include <stdio.h>\n#define M_PI 3.14159265358979323846\n#define EARTH_R_M 6371000.0\n'+fragment+r'''
int main(void) {
    double a,b,c,d;
    while (scanf("%lf %lf %lf %lf",&a,&b,&c,&d)==4)
        printf("%.17g\n",haversine_m(a,b,c,d));
    return 0;
}
'''
        points=[(0,0,0,0),(0,0,0,0.001),(90,0,90,180),(0,179.999999,0,-179.999999),
                (89.999,0,89.999,180),(0,0,0,180),(100,0,0,0)]
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'h.c').write_text(harness,encoding='ascii')
            subprocess.run([shutil.which('gcc'),'-std=c99','-Os','-Wall','-Wextra','-Werror',str(p/'h.c'),'-lm','-o',str(p/'h.exe')],check=True,capture_output=True)
            result=subprocess.run([str(p/'h.exe')],input=''.join(' '.join(map(str,row))+'\n' for row in points),text=True,capture_output=True,check=True)
        distances=[float(x) for x in result.stdout.splitlines()]
        self.assertEqual(distances[0],0)
        self.assertAlmostEqual(distances[1],6371000*math.radians(0.001),places=7)
        self.assertEqual(distances[2],0)
        self.assertAlmostEqual(distances[3],6371000*math.radians(0.000002),places=7)
        self.assertAlmostEqual(distances[4],6371000*math.radians(0.002),places=7)
        self.assertEqual(distances[5],8192)
        self.assertTrue(math.isnan(distances[6]))

if __name__ == '__main__': unittest.main()
