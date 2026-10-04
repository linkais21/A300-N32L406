"""Exact wire replies for shared F39 query formatting, using production C."""
import test_f39_actions as actions


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
   assert(strcmp((char*)r.data,"APN,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa=Success!\r\n")==0);
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
    raise SystemExit(actions.main())
