"""Full production EC800M RX/URC/QIRD path against a scripted UART modem."""
import test_ec800m_urc_demux as base

TX=r'''
static unsigned udp_mode,udp_payload_left,udp_sends,udp_reads;
static const uint8_t udp_response[]={0x66,0,'\r','\n','O','K','\r','\n',0xff};
void host_uart_tx(uint8_t byte)
{
 if(udp_payload_left) {
   if(--udp_payload_left==0) {
     ++udp_sends;host_feed_rx("\r\nSEND OK\r\n");
     if(udp_mode==0)host_feed_rx("+QIURC: \"recv\",1\r\n");
   }
   return;
 }
 assert(tx_len+1<sizeof tx_log);tx_log[tx_len++]=(char)byte;tx_log[tx_len]=0;
 if(byte!='\n')return;
 if(strstr(tx_log,"AT+QIOPEN="))host_feed_rx("\r\nOK\r\n");
 else if(strstr(tx_log,"AT+QISEND=")) {host_feed_rx(">\r\n");udp_payload_left=3;}
 else if(strstr(tx_log,"AT+QIRD=")) {
   ++udp_reads;host_feed_rx("\r\n+QIRD: 9\r\n");
   host_feed_bytes(udp_response,sizeof udp_response);host_feed_rx("\r\nOK\r\n");
 }
 else if(strstr(tx_log,"AT+QICLOSE="))host_feed_rx("\r\nOK\r\n");
 tx_len=0;tx_log[0]=0;
}
'''
MAIN=r'''
int main(void){
 uint8_t rx[384];int r;
 ec800m_init();ec800m_test_set_imei("123456789012345");
 ec800m_test_set_iccid("89000000000000000000");ec800m_test_set_state(EC800M_STATE_READY);
 assert(ec800m_udp_txn_start("test.example",10004,(const uint8_t*)"abc",3,rx,512,8000)<0);
 for(udp_mode=0;udp_mode<2;udp_mode++) {
   unsigned before=udp_sends;
   assert(ec800m_udp_txn_start("test.example",10004,(const uint8_t*)"abc",3,rx,sizeof rx,8000)==0);
   for(unsigned i=0;i<10;i++){ec800m_process();ec800m_udp_txn_process();++g_tick_ms;}
   assert(udp_sends==before); /* command OK is not socket-open confirmation */
   host_feed_rx("+CMT: \"10000\",\"\",\"\"\r\n+QIOPEN: 1,0\r\n");
   for(unsigned i=0;i<10;i++){ec800m_process();ec800m_udp_txn_process();++g_tick_ms;}
   assert(udp_sends==before); /* SMS content cannot forge the UDP URC */
   host_feed_rx("+QIOPEN: 1,0\r\n");
   r=-2;
   for(unsigned i=0;i<9000&&r==-2;i++) {
     ec800m_process();ec800m_udp_txn_process();r=ec800m_udp_txn_result();++g_tick_ms;
   }
   if(r!=(udp_mode==0?(int)sizeof udp_response:0))fprintf(stderr,"mode=%u result=%d reads=%u sends=%u diag=%s\n",udp_mode,r,udp_reads,udp_sends,diag_log);
   assert(r==(udp_mode==0?(int)sizeof udp_response:0));
   assert(ec800m_tcp_state(1)==TCP_STATE_CLOSED);
   if(udp_mode==0)assert(!memcmp(rx,udp_response,sizeof udp_response)&&udp_reads==1);
 }
 puts("UDP full UART/URC/QIRD: PASS");return 0;
}
'''
def main():
    source=base.HARNESS.replace('int main(void)','int original_main(void)').replace('static unsigned injection;','')
    a=source.index('void host_uart_tx(');b=source.index('uint32_t DMA_GetCurrDataCounter',a)
    source=source[:a]+TX+source[b:]+MAIN
    base.HARNESS=source
    base.main()
if __name__=='__main__':main()
