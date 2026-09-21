"""Replay coordinate-free supplied Huada dual-band GSV through real parser."""
import test_production_gnss as replay

MAIN = r'''
#include <stdio.h>
static void line(const char *s){feed(s);gps_process();}
static void sentence(const char *body){char wire[160];unsigned char c=0;for(const char *s=body;*s;s++)c^=*s;snprintf(wire,sizeof wire,"$%s*%02X\r\n",body,c);line(wire);}
int main(void){
 gps_quality_t q;
 line("$BDGSV,8,1,28,3,60,190,39,37,54,202,40,56,53,338,43,8,52,7,44,1*72\r\n");
 line("$BDGSV,8,2,28,27,52,333,46,1,51,128,35,40,44,296,,6,42,163,33,1*73\r\n");
 line("$BDGSV,8,3,28,2,41,238,36,28,38,34,49,10,33,198,33,4,32,112,38,1*49\r\n");
 line("$BDGSV,8,4,28,41,26,123,38,7,25,190,10,9,24,182,,57,24,267,,1*73\r\n");
 line("$BDGSV,8,5,28,33,17,72,43,30,17,276,40,13,16,55,45,23,13,161,17,1*73\r\n");
 line("$BDGSV,8,6,28,32,8,175,,1*7B\r\n");
 assert(!gps_get_quality(&q));
 line("$BDGSV,8,7,28,37,54,202,31,27,52,333,38,28,38,34,37,41,26,123,27,9*43\r\n");
 line("$BDGSV,8,8,28,33,17,72,32,30,17,276,28,23,,,10,9*49\r\n");
 assert(gps_get_diag()->gsv_seen==8&&gps_get_diag()->checksum_fail==0);
 assert(gps_get_quality(&q));
 /* Only primary band: 17 nonzero samples, sum 629. Secondary band not doubled. */
 assert(q.satellites==17&&q.average==37&&q.maximum==49);
 assert(gps_get_diag()->gsv_complete==1);
 g_tick_ms+=5001;assert(!gps_get_quality(&q));
 /* Missing/repeated pages cannot publish a complete sample. */
 sentence("BDGSV,3,1,03,01,40,100,40,1");
 sentence("BDGSV,3,3,03,01,40,100,50,9");assert(!gps_get_quality(&q));
 sentence("BDGSV,3,2,03,02,40,100,30,1");
 sentence("BDGSV,3,2,03,02,40,100,30,1");assert(!gps_get_quality(&q));
 sentence("BDGSV,3,3,03,01,40,100,50,9");
 assert(gps_get_quality(&q)&&q.satellites==2&&q.average==35);
 /* Invalid CN in the secondary band still invalidates the cycle. */
 sentence("BDGSV,2,1,02,01,40,100,40,1");
 sentence("BDGSV,2,2,02,01,40,100,100,9");assert(!gps_get_quality(&q));
 /* A stale partial cycle cannot be completed later. */
 sentence("BDGSV,2,1,02,01,40,100,40,1");g_tick_ms+=5001;
 sentence("BDGSV,2,2,02,01,40,100,50,9");assert(!gps_get_quality(&q));
 puts("Huada multi-band GSV replay PASS");return 0;
}
'''
if __name__=='__main__':
    replay.MAIN=MAIN
    replay.main()
