"""Actual GNSS ISR handoff: ACK fragments coexist with NMEA byte input."""
import test_gps_tx_bounded as tx

CASES = r'''
int main(void) {
    reset_uart();gps_init();
    uint8_t f[10]={0xf1,0xd9,5,1,2,0,0x0b,0x33,0,0},out[10];
    uint32_t seq=gps_agnss_ack_sequence();
    for(unsigned i=0;i<9;i++){gps_rx_isr(f[i]);assert(!gps_agnss_take_ack(&seq,out));}
    gps_rx_isr(f[9]);assert(gps_agnss_take_ack(&seq,out));assert(!memcmp(out,f,10));
    assert(!gps_agnss_take_ack(&seq,out));
    const char *noise="$GNRMC,invalid*00\r\n";
    for(unsigned i=0;noise[i];i++)gps_rx_isr(noise[i]);
    assert(!gps_agnss_take_ack(&seq,out));
    /* A binary payload containing an ACK prefix is not a separate ACK. */
    uint8_t outer[18]={0xf1,0xd9,1,1,10,0};memcpy(outer+6,f,10);
    for(unsigned i=0;i<18;i++)gps_rx_isr(outer[i]);
    assert(!gps_agnss_take_ack(&seq,out));
    gps_rx_isr(0xf1);gps_rx_isr(0xf1);gps_rx_isr(0xd9);
    for(unsigned i=2;i<10;i++)gps_rx_isr(f[i]);
    assert(gps_agnss_take_ack(&seq,out));
    puts("GPS ACK handoff: PASS");return 0;
}
'''

if __name__ == '__main__':
    tx.HARNESS = tx.HARNESS.split('int main(void)')[0] + CASES
    tx.main()
