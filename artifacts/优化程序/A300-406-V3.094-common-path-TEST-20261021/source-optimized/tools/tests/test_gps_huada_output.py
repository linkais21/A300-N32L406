"""Actual UART bytes: ALLYSTAR V2.3.6 section 5.4.2 CFG-MSG, init/wake."""
import test_gps_tx_bounded as tx

CHECK = r'''
static void check_output(void) {
    unsigned mask=0;
    assert(tx_len==33);
    for(unsigned i=0;i<tx_len;i+=11){
        const uint8_t *p=tx_bytes+i;
        assert(p[0]==0xf1&&p[1]==0xd9&&p[2]==6&&p[3]==1);
        assert(p[4]==3&&p[5]==0&&p[6]==0xf0&&p[8]==1);
        uint8_t a=0,b=0;
        for(unsigned j=2;j<9;j++){a+=p[j];b+=a;}
        assert(p[9]==a&&p[10]==b);
        assert(p[7]==0||p[7]==4||p[7]==5);
        mask|=1U<<p[7];
    }
    assert(mask==0x31);
}
int main(void){
    reset_uart();gps_init();check_output();
    reset_uart();gps_resume_after_wake();check_output();
    reset_uart();txde_ready=0;tick_advances=0;
    gps_resume_after_wake();assert(tx_len==0&&reloads>0);
    puts("Huada CFG-MSG init/wake/checksum/bounded failure PASS");return 0;
}
'''
if __name__=='__main__':
    tx.HARNESS=tx.HARNESS.split('int main(void)')[0]+CHECK
    tx.main()
