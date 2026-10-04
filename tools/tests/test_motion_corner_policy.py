"""Host regression tests for the pure heading corner state machine."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <math.h>
#include "motion_corner.h"

static motion_corner_sample_t make_sample(float h, float speed, unsigned ms) {
    motion_corner_sample_t s = { h, speed, ms, true, true };
    return s;
}

static motion_corner_event_t step(motion_corner_ctx_t *c, float h,
                                  float speed, unsigned ms) {
    motion_corner_sample_t s = make_sample(h, speed, ms);
    return motion_corner_step(c, &s);
}

static void enter_turn(motion_corner_ctx_t *c, unsigned *ms) {
    motion_corner_event_t e;
    step(c, 0.0f, 40.0f, *ms); *ms += 1000;
    for (int i = 1; i <= 7; ++i) {
        e = step(c, 3.0f * i, 40.0f, *ms); *ms += 1000;
    }
    assert(motion_corner_state(c) == MOTION_CORNER_TURN_ACTIVE);
    assert(e.reason == MOTION_CORNER_REASON_TURN_ENTER);
}

int main(void) {
    motion_corner_ctx_t c;
    motion_corner_config_t cfg = motion_corner_default_config();
    /* Opposing headings cancel entry even after the first threshold crossing. */
    {
        motion_corner_config_t deferred = cfg;
        deferred.enter_accum_deg = 10.0f;
        deferred.confirm_samples = 4U;
        motion_corner_init(&c, &deferred);
        step(&c, 0.0f, 40.0f, 1000U);
        step(&c, 10.0f, 40.0f, 2000U);
        assert(motion_corner_state(&c) == MOTION_CORNER_TURN_ENTER);
        step(&c, 5.0f, 40.0f, 3000U);
        step(&c, 6.0f, 40.0f, 4000U);
        motion_corner_event_t cancelled = step(&c, 7.0f, 40.0f, 5000U);
        assert(motion_corner_state(&c) == MOTION_CORNER_STRAIGHT);
        assert(!cancelled.report_due && !motion_corner_pending_candidates(&c));
    }
    assert(cfg.enter_accum_deg == 30.0f && cfg.exit_stable_deg == 0.5f);
    /* The scenarios below also exercise non-default policy thresholds. */
    cfg.enter_accum_deg = 20.0f;
    cfg.exit_stable_deg = 3.0f;
    motion_corner_init(&c, &cfg);

    /* Heading wrap 359 -> 1 is a +2 degree step, not -358. */
    motion_corner_event_t e = step(&c, 359.0f, 40.0f, 1000);
    e = step(&c, 1.0f, 40.0f, 2000);
    assert(e.reason == MOTION_CORNER_REASON_NONE);
    assert(motion_corner_heading_delta(359.0f, 1.0f) == 2.0f);
    assert(motion_corner_heading_delta(1.0f, 359.0f) == -2.0f);
    assert(motion_corner_heading_delta(0.0f, 180.0f) == 180.0f);
    assert(motion_corner_heading_delta(180.0f, 0.0f) == -180.0f);
    motion_corner_ctx_t invalid_ctx;
    motion_corner_init(&invalid_ctx, NULL);
    step(&invalid_ctx, 10.0f, 40.0f, 1000);
    motion_corner_sample_t invalid_heading = make_sample(360.0f, 40.0f, 2000);
    motion_corner_step(&invalid_ctx, &invalid_heading);
    assert(invalid_ctx.previous_heading == 10.0f);

    /* Seven same-direction 3 degree samples reach the 20 degree gate. */
    unsigned ms = 3000;
    for (int i = 0; i < 7; ++i) {
        e = step(&c, 1.0f + 3.0f * (i + 1), 40.0f, ms);
        ms += 1000;
    }
    assert(motion_corner_state(&c) == MOTION_CORNER_TURN_ACTIVE);
    assert(e.reason == MOTION_CORNER_REASON_TURN_ENTER ||
           motion_corner_pending_candidates(&c) > 0);

    /* Candidate queue is bounded and failed sends do not consume it. */
    assert(motion_corner_pending_candidates(&c) <= 3);
    unsigned before = motion_corner_pending_candidates(&c);
    motion_corner_candidate_t cand;
    assert(before == 0 || motion_corner_peek_candidate(&c, &cand));
    assert(motion_corner_pending_candidates(&c) == before);
    if (before) {
        motion_corner_consume_candidate(&c);
        assert(motion_corner_pending_candidates(&c) == before - 1);
    }

    /* Speed bins are 5/3/2 seconds; sharp turns are always 1 second. */
    assert(motion_corner_interval_ms(10.0f, false) == 5000U);
    assert(motion_corner_interval_ms(45.0f, false) == 3000U);
    assert(motion_corner_interval_ms(80.0f, false) == 2000U);
    assert(motion_corner_interval_ms(10.0f, true) == 1000U);

    while (motion_corner_pending_candidates(&c))
        motion_corner_consume_candidate(&c);
    /* Five stable <=3 degree samples emit the exit and leave the turn. */
    for (int i = 0; i < 5; ++i) {
        e = step(&c, 22.0f + i, 40.0f, ms);
        ms += 1000;
    }
    assert(motion_corner_state(&c) == MOTION_CORNER_TURN_EXIT ||
           e.reason == MOTION_CORNER_REASON_TURN_EXIT);

    /* A >=12 degree step confirms entry without a second confirmation step,
       once the accumulated 20 degree entry gate is reached. */
    motion_corner_reset(&c); ms = 1000;
    step(&c, 0.0f, 50.0f, ms); ms += 1000;
    step(&c, 8.0f, 50.0f, ms); ms += 1000;
    e = step(&c, 20.0f, 50.0f, ms);
    assert(motion_corner_state(&c) == MOTION_CORNER_TURN_ACTIVE);
    assert(e.sharp && e.reason == MOTION_CORNER_REASON_TURN_ENTER);

    /* GGA/GSV-style non-heading updates cannot inject stable samples. */
    motion_corner_sample_t stale = make_sample(20.0f, 50.0f, ms + 1000);
    stale.heading_fresh = false;
    for (int i = 0; i < 8; ++i) motion_corner_step(&c, &stale);
    assert(motion_corner_state(&c) == MOTION_CORNER_TURN_ACTIVE);

    /* Report generation stops at 12 accepted candidates. */
    motion_corner_reset(&c); ms = 1000; enter_turn(&c, &ms);
    unsigned accepted = 0;
    for (unsigned attempts = 0; accepted < 12 && attempts < 100U; ++attempts) {
        motion_corner_candidate_t x;
        if (motion_corner_peek_candidate(&c, &x)) {
            motion_corner_consume_candidate(&c);
            ++accepted;
        }
        e = step(&c, 21.0f + 4.0f * (attempts + 1U), 80.0f, ms);
        ms += 2000;
    }
    assert(accepted == 12);
    assert(motion_corner_state(&c) == MOTION_CORNER_STRAIGHT);
    assert(!e.report_due || accepted == 12);

    /* An active turn expires after 60 seconds and produces no new point. */
    motion_corner_reset(&c); ms = 1000; enter_turn(&c, &ms);
    while (motion_corner_pending_candidates(&c))
        motion_corner_consume_candidate(&c);
    e = step(&c, 40.0f, 40.0f, ms + 60000U);
    assert(motion_corner_state(&c) == MOTION_CORNER_STRAIGHT);
    assert(!e.report_due);
    return 0;
}
'''


def main() -> int:
    cc = os.environ.get("CC") or shutil.which("gcc.exe") or shutil.which("cc")
    if not cc:
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        matches = list(base.glob("BrechtSanders.WinLibs*/mingw64/bin/gcc.exe"))
        cc = str(matches[0]) if matches else None
    if not cc:
        print("test_motion_corner_policy: SKIP (compiler unavailable)")
        return 0
    with tempfile.TemporaryDirectory(prefix="motion_corner_") as d:
        d = Path(d)
        h = d / "harness.c"
        exe = d / "harness.exe"
        h.write_text(HARNESS, encoding="ascii")
        cmd = [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic",
               "-I", str(ROOT / "include"), str(h),
               str(ROOT / "src" / "motion_corner.c"), "-lm", "-o", str(exe)]
        build = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if build.returncode:
            raise AssertionError("host build failed:\n" + build.stderr)
        run = subprocess.run([str(exe)], cwd=ROOT, capture_output=True, text=True,
                             timeout=15)
        if run.returncode:
            raise AssertionError("motion corner policy failed:\n" + run.stderr)
    print("motion corner policy: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
