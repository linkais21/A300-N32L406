"""Production reconnection over simulated 180-day outage and tick rollover."""
import test_tcp_manager_fip as base
prefix=base.HARNESS.split('int main(void)')[0]
base.HARNESS=prefix+r"""
int main(void){
    (void)check_ota_connection_ownership;
    g_tick_ms=0xffff0000U;ota_state=FOTA_STATE_IDLE;
    reset_endpoint("backup.example",7018U);
    unsigned wraps=0;
    for(unsigned second=0;second<180U*86400U;second++){
        uint32_t previous=g_tick_ms;g_tick_ms+=1000U;
        if(g_tick_ms<previous)++wraps;
        tcp_manager_process();
        assert(!tcp_manager_ch_online(TCP_CH_MAIN));
        assert(!tcp_manager_ch_online(TCP_CH_BACKUP));
    }
    assert(wraps>=3 && open_calls>200000U && open_calls<320000U);
    unsigned retries=open_calls;
    channel_state[TCP_CH_MAIN]=channel_state[TCP_CH_BACKUP]=TCP_STATE_OPEN;
    for(unsigned i=0;i<5;i++){g_tick_ms+=120001U;tcp_manager_process();}
    assert(tcp_manager_ch_online(TCP_CH_MAIN)&&tcp_manager_ch_online(TCP_CH_BACKUP));
    assert(open_calls<=retries+2U);
    return 0;
}
"""
if __name__=='__main__':raise SystemExit(base.main())
