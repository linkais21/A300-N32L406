"""Exercise real legacy console parsing, including rejection without mutation."""
import test_at_config_serial_f39 as serial

EXTRA = r'''
    line("TIMER=10,60");
    assert(config.report_moving_s == 10 && config.report_stopped_s == 60);
    const char *bad_numbers[] = {"", "-1", "+1", "65536", "99999999999999999999", "10x", " 10"};
    for (unsigned i=0; i<sizeof bad_numbers/sizeof bad_numbers[0]; ++i) {
        char command[100];
        snprintf(command,sizeof command,"TIMER=%s,60",bad_numbers[i]);
        line(command);
        assert(strstr(console,"ERR") != NULL);
        assert(config.report_moving_s == 10 && config.report_stopped_s == 60);
        snprintf(command,sizeof command,"TIMER=20,%s",bad_numbers[i]);
        line(command);
        assert(strstr(console,"ERR") != NULL);
        assert(config.report_moving_s == 10 && config.report_stopped_s == 60);
        snprintf(command,sizeof command,"SERVER=example.test,%s",bad_numbers[i]);
        line(command); assert(strstr(console,"ERR") != NULL);
        snprintf(command,sizeof command,"BSERVER=example.test,%s",bad_numbers[i]);
        line(command); assert(strstr(console,"ERR") != NULL);
        snprintf(command,sizeof command,"HEARTBEAT=%s",bad_numbers[i]);
        line(command); assert(strstr(console,"ERR") != NULL);
    }
    line("TIMER=0,65535");
    assert(config.report_moving_s == 0 && config.report_stopped_s == 65535);
    line("TIMER=1,4");
    assert(config.report_moving_s == 5 && config.report_stopped_s == 5);
    line("HEARTBEAT=10"); assert(config.heartbeat_s == 600);
    line("HEARTBEAT=1"); assert(config.heartbeat_s == 60);
    line("SERVER=example.test,65535"); assert(strstr(console,"OK"));
    line("BSERVER=example.test,1"); assert(strstr(console,"OK"));
'''

if __name__ == "__main__":
    anchor = '    /* A genuinely unknown line is still reported as unknown. */'
    assert anchor in serial.HARNESS
    serial.HARNESS = serial.HARNESS.replace(anchor, EXTRA + anchor, 1)
    raise SystemExit(serial.main())
