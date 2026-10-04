"""A replay ACK belongs to the sending channel and connection generation."""
import test_blind_zone_replay as replay

CHECKS = r'''
    /* Authenticate backup while main stays online. */
    s_gps.valid = false;
    strcpy(s_config.backup_auth_code, "AUTH");
    s_backup_online = true;
    jt808_process();
    unescape(decoded);
    assert(decoded[0] == 0x01U && decoded[1] == 0x02U);
    inject_ack_ch(EC800M_CH_BACKUP, sent_serial(), MSG_TERMINAL_AUTH, 0U, 5U);
    assert(jt808_channel_online(EC800M_CH_MAIN));
    assert(jt808_channel_online(EC800M_CH_BACKUP));
    push_record(0x31U);
    blind_zone_replay_process();
    assert(s_last_send_channel == EC800M_CH_MAIN);
    replay_serial = sent_serial();
    inject_ack_ch(EC800M_CH_BACKUP, replay_serial, 0x0704U, 0U, 5U);
    blind_zone_replay_process();
    assert(s_queue_count == 1U && s_consume_count == 4U);
    blind_zone_replay_on_general_ack(EC800M_CH_MAIN, s_session_generation - 1U,
                                     replay_serial, 0x0704U, 0U);
    blind_zone_replay_process();
    assert(s_queue_count == 1U && s_consume_count == 4U);
    inject_ack(replay_serial, 0x0704U, 0U, 5U);
    blind_zone_replay_process();
    assert(s_queue_count == 0U && s_consume_count == 5U);

    push_record(0x41U);
    blind_zone_replay_process();
    replay_serial = sent_serial();
    /* Main reconnects, but backup never disconnected. */
    ++s_session_generation;
    assert(!jt808_channel_online(EC800M_CH_MAIN));
    assert(jt808_channel_online(EC800M_CH_BACKUP));
    inject_ack_ch(EC800M_CH_BACKUP, replay_serial, 0x0704U, 0U, 5U);
    blind_zone_replay_process();
    assert(s_queue_count == 1U && s_consume_count == 5U);
    assert(s_last_send_channel == EC800M_CH_BACKUP);
    replay_serial2 = sent_serial();
    assert(replay_serial2 != replay_serial);
    inject_ack_ch(EC800M_CH_BACKUP, replay_serial2, 0x0704U, 0U, 5U);
    blind_zone_replay_process();
    assert(s_queue_count == 0U && s_consume_count == 6U);
'''

def main():
    original = replay.HARNESS
    source = original.replace('return ch <= EC800M_CH_BACKUP ? s_session_generation : 0U;',
                              'return ch == EC800M_CH_MAIN ? s_session_generation : 1U;')
    needle = '    puts("test_blind_zone_replay: PASS");'
    assert needle in source
    replay.HARNESS = source.replace(needle, CHECKS + needle)
    try:
        result = replay.compile_and_run(replay.ROOT / 'src/blind_zone_replay.c')
    finally:
        replay.HARNESS = original
    print(result.stdout + result.stderr, end='')
    if result.returncode:
        return result.returncode
    print('test_blind_zone_ack_channel: PASS')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
