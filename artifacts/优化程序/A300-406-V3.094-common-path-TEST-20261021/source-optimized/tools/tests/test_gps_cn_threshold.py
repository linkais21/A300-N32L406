"""Count qualifying primary-band satellites through the real GSV parser."""
import test_production_gnss as replay

MAIN = r'''
#include <stdio.h>
static void sentence(const char *body){char wire[160];unsigned char c=0;for(const char *s=body;*s;s++)c^=*s;snprintf(wire,sizeof wire,"$%s*%02X\r\n",body,c);feed(wire);gps_process();}
static void cycle(void){
 sentence("GBGSV,2,1,08,01,40,100,38,02,40,110,38,03,40,120,38,04,40,130,38,1");
 sentence("GBGSV,2,2,08,05,40,100,38,06,40,110,10,07,40,120,10,08,40,130,,1");
}
int main(void){
 gps_quality_t q;
 assert(gps_set_quality_cn_threshold(38));
 cycle();assert(gps_get_quality(&q));
 /* Five exactly-38 satellites pass despite an average of 30 and max of 38. */
 assert(q.cn_threshold==38&&q.qualified==5&&q.average==30&&q.maximum==38);
 unsigned seq=q.sequence;
 assert(gps_set_quality_cn_threshold(38));
 assert(gps_get_quality(&q)&&q.sequence==seq&&q.qualified==5);
 /* Secondary bands and mixed GN summaries must not double count. */
 sentence("GBGSV,1,1,01,01,40,100,50,3");
 sentence("GNGSV,1,1,01,01,40,100,50,1");
 assert(gps_get_quality(&q)&&q.qualified==5);
 sentence("GPGSV,1,1,01,11,40,100,38,1");
 assert(gps_get_quality(&q)&&q.qualified==6);
 /* A new threshold cannot reinterpret or reuse an old/partial cycle. */
 assert(gps_set_quality_cn_threshold(39));
 assert(!gps_get_quality(&q)&&q.cn_threshold==39&&q.qualified==0);
 cycle();assert(gps_get_quality(&q)&&q.qualified==0);
 assert(!gps_set_quality_cn_threshold(19));
 assert(!gps_set_quality_cn_threshold(51));
 assert(gps_get_quality(&q)&&q.cn_threshold==39);
 assert(gps_set_quality_cn_threshold(38));
 sentence("GBGSV,2,1,08,01,40,100,38,02,40,110,38,03,40,120,38,04,40,130,38,1");
 assert(!gps_get_quality(&q)&&q.qualified==0);
 assert(gps_set_quality_cn_threshold(37));
 sentence("GBGSV,2,2,08,05,40,100,38,06,40,110,10,07,40,120,10,08,40,130,,1");
 assert(!gps_get_quality(&q)&&q.qualified==0);
 cycle();assert(gps_get_quality(&q)&&q.qualified==5);
 g_tick_ms+=5001;assert(!gps_get_quality(&q)&&q.qualified==0);
 g_tick_ms=0xfffffffeU;cycle();g_tick_ms=3;
 assert(gps_get_quality(&q)&&q.qualified==5);
 puts("per-satellite CN threshold/count/freshness/band isolation PASS");return 0;
}
'''

if __name__ == '__main__':
    replay.MAIN = MAIN
    replay.main()
