"""Exercise actual C confirmation at quiet troughs and the no-fix wake edge."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "work_mode.h"

static void drain(void) {
    work_mode_action_t action;
    while (work_mode_next_action(&action)) {}
}
static void step(uint32_t ms, bool hit) {
    work_mode_input_t in = { .now_s=ms/1000U, .now_ms=ms,
        .acc_high=false, .vibration_hit=hit, .vibration_sample_valid=true,
        .gps_valid=false, .rtc_wake=false, .alarm_bits=0U };
    work_mode_step(&in);
}
static void sleep_init(void) {
    const work_mode_config_t cfg = {30U,180U,180U,300U,6U};
    work_mode_init(&cfg,0U,true);
    drain();
    work_mode_input_t in = {.now_s=300U, .acc_high=false, .gps_valid=true};
    work_mode_step(&in);
    assert(work_mode_state()==WORK_MODE_STATIONARY_SLEEP);
    drain();
}
static void assert_one_on_entry(void) {
    work_mode_action_t action;
    unsigned on=0, gps=0, entry=0;
    assert(work_mode_state()==WORK_MODE_REALTIME);
    assert(work_mode_logical_acc());
    while (work_mode_next_action(&action)) {
        if (action.type==WORK_ACTION_SET_LOGICAL_ACC && action.acc_on) ++on;
        if (action.type==WORK_ACTION_GPS_ON) ++gps;
        if (action.type==WORK_ACTION_REPORT_ENTRY && action.acc_on) ++entry;
    }
    assert(on==1U && gps==1U && entry==1U);
}
int main(int argc, char **argv) {
    assert(argc==2);
    sleep_init();
    if (strcmp(argv[1],"trough")==0) {
        /* Seven real hits and three quiet samples each two-second cycle.
         * 0.6s troughs remain below the 1s motion gap and density exceeds 2/3. */
        for (unsigned n=0U;n<=30U;++n) {
            step(300200U+n*200U,(n%10U)<7U);
            if (n<30U) assert(work_mode_state()==WORK_MODE_STATIONARY_SLEEP);
        }
        assert_one_on_entry();
    } else if (strcmp(argv[1],"deadline_miss")==0) {
        for (unsigned n=0U;n<=30U;++n) {
            step(300200U+n*200U,n<30U);
            if (n<30U) assert(work_mode_state()==WORK_MODE_STATIONARY_SLEEP);
        }
        assert_one_on_entry();
        step(306400U,false);
        work_mode_action_t action;
        while (work_mode_next_action(&action))
            assert(action.type!=WORK_ACTION_REPORT_ENTRY);
    } else if (strcmp(argv[1],"gap")==0) {
        step(300200U,true);
        for (unsigned n=1U;n<=6U;++n) step(300200U+n*200U,false);
        assert(work_mode_vibration_hits()==0U);
        for (unsigned n=0U;n<30U;++n) step(301600U+n*200U,true);
        assert(work_mode_state()==WORK_MODE_STATIONARY_SLEEP);
        step(307600U,true);
        assert_one_on_entry();
    } else if (strcmp(argv[1],"sparse")==0) {
        for (unsigned n=0U;n<=70U;++n) step(300200U+n*200U,(n%3U)==0U);
        assert(work_mode_state()==WORK_MODE_STATIONARY_SLEEP);
        assert(!work_mode_logical_acc());
    } else if (strcmp(argv[1],"stale_hit")==0) {
        for (unsigned n=0U;n<25U;++n) step(300200U+n*200U,true);
        for (unsigned n=25U;n<=31U;++n) step(300200U+n*200U,false);
        assert(work_mode_state()==WORK_MODE_STATIONARY_SLEEP);
    } else if (strcmp(argv[1],"wrap")==0) {
        for (unsigned n=0U;n<=30U;++n) {
            step(0xfffff000U+n*200U,(n%10U)<7U);
            if (n<30U) assert(work_mode_state()==WORK_MODE_STATIONARY_SLEEP);
        }
        assert_one_on_entry();
    } else assert(!"unknown scenario");
    return 0;
}
'''


class ConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('CC') or shutil.which('gcc') or shutil.which('cc')
        if not compiler:
            raise AssertionError('Host C compiler required')
        cls.temp = tempfile.TemporaryDirectory(prefix='vibration_boundary_')
        temp = Path(cls.temp.name)
        harness = temp/'h.c'
        harness.write_text(HARNESS, encoding='ascii')
        cls.exe = temp/'h.exe'
        subprocess.run([compiler,'-std=c99','-Wall','-Wextra','-Werror','-I',str(ROOT/'include'),
                        str(harness),str(ROOT/'src/work_mode.c'),'-o',str(cls.exe)],
                       check=True, timeout=60)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def case(self, name):
        run = subprocess.run([str(self.exe),name], capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode,0,run.stderr)

    def test_motion_troughs_confirm_at_six_seconds_without_fix(self): self.case('trough')
    def test_deadline_threshold_miss_does_not_delay_entry(self): self.case('deadline_miss')
    def test_over_one_second_gap_requires_new_episode(self): self.case('gap')
    def test_sparse_spikes_cannot_authorize_wake(self): self.case('sparse')
    def test_old_dense_hits_do_not_authorize_after_motion_stops(self): self.case('stale_hit')
    def test_six_second_window_survives_millisecond_wrap(self): self.case('wrap')


if __name__ == '__main__':
    unittest.main(verbosity=2)
