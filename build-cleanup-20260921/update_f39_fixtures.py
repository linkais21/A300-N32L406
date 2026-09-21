from pathlib import Path
import shutil
root=Path(__file__).resolve().parents[1]
extra='''#include "f39_reply.h"
#include "fota.h"
#include "log_platform.h"
fota_state_t fota_get_state(void) { return FOTA_STATE_IDLE; }
int log_platform_send_result(void) { return 0; }'''
for name in ('test_f39_actions.py','test_f39_end_to_end.py','test_at_config_serial_f39.py'):
    p=root/'tools/tests'/name
    dest=root/'build-cleanup-20260921/before'/name
    assert not dest.exists()
    shutil.copy2(p,dest)
    s=p.read_text(encoding='utf-8')
    assert 'fota_get_state(void)' not in s
    s=s.replace('#include "f39_reply.h"',extra)
    p.write_text(s,encoding='utf-8',newline='\n')
