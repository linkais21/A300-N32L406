"""Exercise production NMEA drop causes with UART status injection."""
import test_gps_ntp_apply as host


def main():
    prefix = host.HARNESS.split("int main(void){", 1)[0]
    prefix = prefix.replace("volatile uint32_t g_tick_ms = 1000U;",
                            "volatile uint32_t g_tick_ms = 1000U;\nstatic int overrun, rx_ready, reads;")
    prefix = prefix.replace("(void)u;(void)f;return 0;", "(void)u;(void)f;return rx_ready;")
    prefix = prefix.replace("return f==USART_FLAG_TXDE||f==USART_FLAG_TXC;",
                            "return f==USART_FLAG_OREF ? overrun : "
                            "(f==USART_FLAG_TXDE||f==USART_FLAG_TXC);")
    prefix = prefix.replace("(void)u;return 0U;", "(void)u;++reads;overrun=0;rx_ready=0;return '$';")
    host.HARNESS = prefix + r'''
void UART4_IRQHandler(void);
int main(void) {
    const char *rmc="$GPRMC,123519,A,4807.038,N,01131.000,E,22.4,84.4,230394,003.1,W*6A\r\n";
    const volatile gps_diag_t *d=gps_get_diag();
    gps_init();
    feed(rmc);feed(rmc);feed(rmc);
    assert(d->drop==1 && d->drop_queue==1 && d->drop_length==0);
    gps_process();gps_process();
    assert(d->parsed==2 && gps_get_data()->valid);
    gps_rx_isr('$');for(unsigned i=0;i<150;i++)gps_rx_isr('A');gps_rx_isr('\n');
    assert(d->drop==2 && d->drop_queue==1 && d->drop_length==1);
    feed(rmc);gps_process();assert(d->parsed==3);
    overrun=1;UART4_IRQHandler();
    assert(d->overrun==1 && d->drop==2);
    UART4_IRQHandler();assert(d->overrun==1);
    uint32_t rx_before=d->rx_bytes;
    overrun=1;rx_ready=1;reads=0;UART4_IRQHandler();
    assert(d->overrun==2 && reads==1);
    assert(d->rx_bytes==rx_before+1);
    UART4_IRQHandler();assert(d->overrun==2 && reads==1);
    gps_init();
    assert(d->drop==0 && d->drop_queue==0 && d->drop_length==0 && d->overrun==0);
    feed(rmc);gps_process();assert(d->parsed==1);
    return 0;
}
'''
    result = host.main()
    if result == 0:
        print("test_gps_drop_diagnostics: PASS")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
