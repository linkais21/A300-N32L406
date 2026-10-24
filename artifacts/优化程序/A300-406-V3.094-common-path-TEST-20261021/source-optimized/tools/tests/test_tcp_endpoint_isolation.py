"""Endpoint reconnect must preserve the opposite live session, including OTA deferral."""
import test_tcp_manager_fip as base

checks = r'''
    ota_state = FOTA_STATE_IDLE;
    reset_endpoint("backup.example", 7018U);
    channel_state[TCP_CH_MAIN] = TCP_STATE_OPEN;
    channel_state[TCP_CH_BACKUP] = TCP_STATE_OPEN;
    tcp_manager_process();
    for (unsigned n=0; n<2; ++n) {
        uint8_t ch = n == 0 ? TCP_CH_MAIN : TCP_CH_BACKUP;
        uint8_t other = n == 0 ? TCP_CH_BACKUP : TCP_CH_MAIN;
        uint32_t gen = tcp_manager_session_generation(other);
        unsigned closed = close_calls;
        ota_state = FOTA_STATE_DOWNLOADING;
        tcp_manager_reconnect_channels((uint8_t)(1U << ch));
        tcp_manager_process();
        assert(close_calls == closed && tcp_manager_ch_online(other));
        ota_state = FOTA_STATE_IDLE;
        tcp_manager_process();
        assert(close_calls == closed + 1U);
        assert(tcp_manager_ch_online(other));
        assert(tcp_manager_session_generation(other) == gen);
        tcp_manager_process();
        assert(tcp_manager_ch_online(ch));
    }
'''

if __name__ == '__main__':
    base.HARNESS = base.HARNESS.replace('    size_t i;', '    size_t i;\n' + checks)
    raise SystemExit(base.main())
