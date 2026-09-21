"""Replay complete/interleaved GSV cycles through actual GPS parser."""
import tempfile
import subprocess
from pathlib import Path
import test_nmea_replay as nmea
from test_f39_actions import find_compiler
ROOT=nmea.ROOT
MAIN=r'''
#include <stdio.h>
static void sentence(const char *body){char wire[160];unsigned char c=0;for(const char *s=body;*s;s++)c^=*s;snprintf(wire,sizeof wire,"$%s*%02X\r\n",body,c);feed(wire);gps_process();}
int main(void){
 gps_quality_t q;
 assert(!gps_get_quality(&q));
 sentence("GPGSV,2,1,05,01,40,100,30,02,40,110,40,03,40,120,,04,40,130,20");
 assert(!gps_get_quality(&q));
 sentence("BDGSV,1,1,01,11,40,100,50");
 sentence("GPGSV,2,2,05,05,40,100,35");
 assert(gps_get_quality(&q));assert(q.satellites==5&&q.average==35&&q.maximum==50);
 unsigned seq=q.sequence;
 /* Duplicate fragment never counts as a new sample. */
 sentence("GPGSV,2,2,05,05,40,100,35");assert(gps_get_quality(&q)&&q.sequence==seq);
 /* Partial next cycle invalidates that talker's previous published cycle. */
 sentence("GPGSV,2,1,05,01,40,100,99,02,40,110,99,03,40,120,,04,40,130,99");
 assert(gps_get_quality(&q)&&q.satellites==1&&q.average==50);
 /* Invalid C/N field cannot create a valid complete cycle. */
 sentence("GPGSV,2,2,05,05,40,100,100");assert(gps_get_quality(&q)&&q.satellites==1);
 g_tick_ms+=6000;assert(!gps_get_quality(&q)&&q.satellites==0);
 /* GSV with signal ID supported; GN mixed and constellation cycles are not added together. */
 sentence("GNGSV,1,1,01,11,40,100,40,1");assert(gps_get_quality(&q)&&q.satellites==1);
 sentence("GPGSV,1,1,01,11,40,100,40,1");assert(gps_get_quality(&q)&&q.satellites==1);
 seq=q.sequence;g_tick_ms++;
 sentence("GNGSV,1,1,01,11,40,100,40,1");assert(gps_get_quality(&q)&&q.sequence==seq);
 /* Bad checksum has no effect. */
 seq=q.sequence;feed("$GPGSV,1,1,01,11,40,100,99*00\r\n");gps_process();assert(gps_get_quality(&q)&&q.sequence==seq);
 g_tick_ms=0xfffffffeU;sentence("GPGSV,1,1,01,11,40,100,35");g_tick_ms=3;assert(gps_get_quality(&q));
 sentence("GPGGA,123520,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,");
 assert(gps_get_data()->valid);
 assert(gps_quality_fix_fresh());
 g_tick_ms+=6000;
 sentence("GPRMC,123521,A,4807.038,N,01131.000,E,0,0,230394,,");
 assert(gps_get_data()->valid&&!gps_quality_fix_fresh());
 sentence("GPRMC,123521,V,,,,,,,230394,,");assert(!gps_get_data()->valid);
 sentence("GPGGA,123522,,,,,0,00,99.9,,,,,,");assert(gps_get_data()->fix_quality==0);
 puts("production GSV PASS");return 0;
}
'''
def main():
 with tempfile.TemporaryDirectory() as tmp:
  p=Path(tmp)
  for name,body in {'n32l40x.h':nmea.N32,'config.h':nmea.CONFIG,'hw_init.h':'#include "n32l40x.h"\nvoid delay_ms(uint32_t);\n','debug_uart.h':'int dbg_printf(const char*,...);\n','h.c':nmea.HARNESS.split('int main(void)')[0]+MAIN}.items(): (p/name).write_text(body)
  subprocess.run([find_compiler(),'-std=c99','-Wall','-Wextra','-Werror','-I',str(p),'-I',str(ROOT/'include'),str(p/'h.c'),str(ROOT/'src/gps.c'),'-lm','-o',str(p/'h.exe')],check=True)
  subprocess.run([str(p/'h.exe')],check=True)
if __name__=='__main__':main()
