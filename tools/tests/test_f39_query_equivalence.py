"""Exact wire replies for shared F39 query formatting, using production C."""
import test_f39_actions as actions


SPEC = r'''
 /* Command spec sheet1: every set command confirms with its stored value. */
 { static const char *cmd[] = {
     "HBT,120", "SPEED,120", "FREQ,30,180", "GPSDUP,0", "GPSDUP,1",
     "MLG,500", "VIBSENS,30", "GPSBDS,3", "GMTSET,W0500",
     "MODEL,T360-A300", "IP,8.8.8.8,8888", "FIP,8.8.8.8,8888", "FIP,0",
     "APN,cmiot,user,password", "APN,AUTO", "APN,0",
     "DUALSET,HBT:180*FREQ:30,180"};
   static const char *want[] = {
     "HBT,120=Success!\r\n", "SPEED,120=Success!\r\n",
     "FREQ,30,180=Success!\r\n", "GPSDUP,0=Success!\r\n",
     "GPSDUP,1=Success!\r\n", "MLG,500=Success!\r\n",
     "VIBSENS,30=Success!\r\n", "GPSBDS,3=Success!\r\n",
     "GMTSET,W0500=Success!\r\n", "MODEL,T360-A300=Success!\r\n",
     "IP,8.8.8.8,8888=Success!\r\n", "FIP,8.8.8.8,8888=Success!\r\n",
     "FIP,0=Success!\r\n", "APN,cmiot,user,password=Success!\r\n",
     "APN,AUTO=Success!\r\n", "APN,0=Success!\r\n",
     "DUALSET,HBT:180*FREQ:30,180=Success!\r\n"};
   device_config_t spec=seed(); spy_t sp=s; f39_reply_t rr; unsigned j;
   for(j=0;j<sizeof(cmd)/sizeof(cmd[0]);++j) {
     assert(run(cmd[j],&spec,&sp,&rr)==F39_RESULT_OK);
     assert(strcmp((char*)rr.data,want[j])==0);
   }
   assert(run("APN",&spec,&sp,&rr)==F39_RESULT_OK);
   assert(strcmp((char*)rr.data,"APN,AUTO=Success!\r\n")==0);
   assert(run("APN,cmiot,,",&spec,&sp,&rr)==F39_RESULT_OK);
   assert(run("APN",&spec,&sp,&rr)==F39_RESULT_OK);
   assert(strcmp((char*)rr.data,"APN,cmiot,,=Success!\r\n")==0);
 }

'''

EXTRA = r'''
 { static const char *commands[] = {
     "HBT", "SPEED", "GPSDUP", "MLG", "GPSBDS", "VIBSENS",
     "MODEL", "APN", "CAR"};
   static const char *expected[] = {
     "HBT,65535=Success!\r\n", "SPEED,65535=Success!\r\n",
     "GPSDUP,0=Success!\r\n", "MLG,42949672=Success!\r\n",
     "GPSBDS,255=Success!\r\n", "VIBSENS,255=Success!\r\n",
     "MODEL,ABCDEFGHIJKLMNOPQRST=Success!\r\n",
     "APN,AUTO=Success!\r\n", "CAR,=Success!\r\n"};
   device_config_t edge=seed(); unsigned j;
   edge.heartbeat_s=UINT16_MAX; edge.speed_limit_kmh=UINT16_MAX;
   edge.sleep_report_mode=1; edge.mileage_m=UINT32_MAX;
   edge.gpsbds_mode=UINT8_MAX; edge.vib_sens=UINT8_MAX;
   strcpy(edge.terminal_model,"ABCDEFGHIJKLMNOPQRST"); edge.autoapn_en=1;
   for(j=0;j<sizeof(commands)/sizeof(commands[0]);++j) {
     assert(run(commands[j],&edge,&s,&r)==F39_RESULT_OK);
     assert(strcmp((char*)r.data,expected[j])==0);
     assert(r.len==strlen(expected[j]));
   }
   edge.autoapn_en=0; memset(edge.apn,'a',sizeof(edge.apn)-1);
   edge.apn[sizeof(edge.apn)-1]=0;
   assert(run("APN",&edge,&s,&r)==F39_RESULT_OK);
   assert(strcmp((char*)r.data,"APN,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,,=Success!\r\n")==0);
   edge.heartbeat_s=0;
   assert(run("HBT",&edge,&s,&r)==F39_RESULT_OK);
   assert(strcmp((char*)r.data,"HBT,0=Success!\r\n")==0);
   memset(edge.terminal_model,'x',sizeof(edge.terminal_model));
   assert(run("MODEL",&edge,&s,&r)==F39_RESULT_INVALID);
 }
'''

if __name__ == "__main__":
    anchor = ' assert(run("PARAM",&c,&s,&r)==F39_RESULT_OK);'
    assert anchor in actions.HARNESS
    actions.HARNESS = actions.HARNESS.replace(anchor, EXTRA + anchor, 1)
    end = '\n return 0; }'
    assert actions.HARNESS.count(end) == 1
    actions.HARNESS = actions.HARNESS.replace(end, SPEC + end, 1)
    raise SystemExit(actions.main())
