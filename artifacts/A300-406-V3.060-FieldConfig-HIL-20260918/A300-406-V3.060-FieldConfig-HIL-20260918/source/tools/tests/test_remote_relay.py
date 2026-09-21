"""Exercise 0x8105 through the real frame parser and shared F39 executor."""
from pathlib import Path
import test_jt808_text_command as text_test
import test_f39_actions as actions

ROOT = Path(__file__).resolve().parents[2]

CHECKS = r'''
    {
        uint8_t body[2] = {0x64U, 0U};
        unsigned n;
        exec_calls = 0U;
        inject(0U, 0x8105U, body, 1U);
        assert(exec_calls == 1U && strcmp(exec_text, "RELAY,1") == 0);
        assert(msg(0U, &sn0, decoded, &length) == 1U && decoded[16] == 0U);
        assert(decoded[14] == 0x81U && decoded[15] == 0x05U);
        exec_result = false;
        inject(0U, 0x8105U, body, 1U);
        assert(msg(0U, &sn0, decoded, &length) == 1U && decoded[16] == 1U);
        exec_result = true;
        body[0] = 0x65U; n = sends[0];
        inject(3U, 0x8105U, body, 1U);
        assert(strcmp(exec_text, "RELAY,0") == 0 && sends[0] == n);
        assert(msg(3U, &sn3, decoded, &length) == 1U && decoded[16] == 0U);
        n = exec_calls;
        inject(0U, 0x8105U, body, 2U);
        assert(exec_calls == n);
        assert(msg(0U, &sn0, decoded, &length) == 1U && decoded[16] == 2U);
        inject(0U, 0x8105U, body, 0U);
        assert(exec_calls == n);
        assert(msg(0U, &sn0, decoded, &length) == 1U && decoded[16] == 2U);
        body[0] = 1U;
        inject(0U, 0x8105U, body, 1U);
        assert(exec_calls == n);
        assert(msg(0U, &sn0, decoded, &length) == 1U && decoded[16] == 3U);
        ++generation[0];
        body[0] = 0x64U; n = sends[0];
        inject(0U, 0x8105U, body, 1U);
        assert(exec_calls == 3U && sends[0] == n);
    }
'''

def main():
    # Reuse session authentication and framing fixtures, not a second parser.
    main_source = text_test.TEXT_MAIN
    main_source = main_source.replace('    return 0;', '    test_rx_overlap();\n' + CHECKS + '\n    return 0;')
    original = text_test.TEXT_MAIN
    text_test.TEXT_MAIN = main_source
    try:
        result = text_test.main()
    finally:
        text_test.TEXT_MAIN = original
    if result:
        return result
    # Existing safety tests plus malformed commands and idempotent recovery.
    extra = r'''
 { device_config_t q=seed(); spy_t z={0}; f39_reply_t rr;
   z.gps_ok=true; z.speed=0;
   assert(run("RELAY,1,extra",&q,&z,&rr)!=F39_RESULT_OK && z.relays==0);
   assert(run("RELAY,0,extra",&q,&z,&rr)!=F39_RESULT_OK && z.relays==0);
   assert(run("RELAY,1",&q,&z,&rr)==F39_RESULT_OK && z.relay);
   assert(run("RELAY,1",&q,&z,&rr)==F39_RESULT_OK && z.relay);
   z.gps_ok=false; z.speed=INFINITY;
   assert(run("RELAY,0",&q,&z,&rr)==F39_RESULT_OK && !z.relay);
   assert(run("RELAY,0",&q,&z,&rr)==F39_RESULT_OK && !z.relay);
 }
'''
    original = actions.HARNESS
    actions.HARNESS = original.replace(' return 0; }', extra + ' return 0; }')
    try:
        result = actions.main()
    finally:
        actions.HARNESS = original
    if not result:
        print('test_remote_relay: PASS')
    return result

if __name__ == '__main__':
    raise SystemExit(main())
