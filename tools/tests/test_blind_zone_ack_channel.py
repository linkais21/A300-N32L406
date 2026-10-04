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
    g_tick_ms += 1000U;
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
    g_tick_ms += 1000U;
    blind_zone_replay_process();
    replay_serial = sent_serial();
    /* Main reconnects, but backup never disconnected. */
    ++s_session_generation;
    assert(!jt808_channel_online(EC800M_CH_MAIN));
    assert(jt808_channel_online(EC800M_CH_BACKUP));
    inject_ack_ch(EC800M_CH_BACKUP, replay_serial, 0x0704U, 0U, 5U);
    blind_zone_replay_process();
    assert(s_queue_count == 1U && s_consume_count == 5U);
    assert(s_last_send_channel == EC800M_CH_MAIN);
    /* Backup must neither receive nor consume main's backlog. */
    sends = s_send_count;
    uint8_t dummy = 0U;
    assert(jt808_send_raw_tracked(MSG_BLIND_ZONE_BATCH, &dummy, 1U, &replay_serial2) != 0);
    assert(s_send_count == sends);
    s_gps.valid = true;
    for (unsigned n=0; n<3; ++n) {
        g_tick_ms += 10000U;
        s_gps.last_update_ms = g_tick_ms;
        assert(jt808_send_location_work_mode(0U, false, 100U+n) == 0);
        assert(s_last_send_channel == EC800M_CH_BACKUP);
        assert(s_queue_count == 2U+n);
        sends = s_send_count;
        blind_zone_replay_process();
        assert(s_send_count == sends && s_consume_count == 5U);
    }
    s_gps.valid = false;
    jt808_process();
    memcpy(s_sent, main_packet, main_packet_len); s_sent_length = main_packet_len;
    inject_ack_ch(EC800M_CH_MAIN, sent_serial(), MSG_TERMINAL_AUTH, 0U, 5U);
    assert(jt808_channel_online(EC800M_CH_MAIN));
    blind_zone_replay_process();
    assert(s_last_send_channel == EC800M_CH_MAIN);
    replay_serial2 = sent_serial();
    inject_ack_ch(EC800M_CH_BACKUP, replay_serial2, 0x0704U, 0U, 5U);
    blind_zone_replay_process();
    assert(s_queue_count == 4U && s_consume_count == 5U);
    inject_ack_ch(EC800M_CH_MAIN, replay_serial2, 0x0704U, 0U, 5U);
    blind_zone_replay_process();
    assert(s_queue_count == 0U && s_consume_count == 6U);
'''

def main():
    original = replay.HARNESS
    source = original.replace('return ch <= EC800M_CH_BACKUP ? s_session_generation : 0U;',
                              'return ch == EC800M_CH_MAIN ? s_session_generation : 1U;')
    source = source.replace('static uint8_t s_sent[1024];',
        'static uint8_t s_sent[1024], main_packet[1024]; static uint16_t main_packet_len;')
    source = source.replace('s_last_send_channel = ch;',
        's_last_send_channel = ch; if(ch == EC800M_CH_MAIN) { memcpy(main_packet,data,length); main_packet_len=length; }')
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
