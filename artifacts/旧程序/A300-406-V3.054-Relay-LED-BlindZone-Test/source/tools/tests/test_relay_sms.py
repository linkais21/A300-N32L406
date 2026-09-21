"""Real SMS ingress -> F39 safety policy -> relay GPIO, without a modem."""
import subprocess
import tempfile
from pathlib import Path
import test_f39_actions as actions

ROOT = Path(__file__).resolve().parents[2]
MAIN = r'''
#include "relay.h"
#include "sms_ingress.h"
static device_config_t config;
static spy_t spy;
static f39_reply_t response;
static bool result;
static unsigned output_level;
void GPIO_SetBits(void *port,unsigned pin) { assert(port==(void*)1 && pin==2048U); output_level=1U; }
void GPIO_ResetBits(void *port,unsigned pin) { assert(port==(void*)1 && pin==2048U); output_level=0U; }
static void command(const char *from,const uint8_t *data,uint16_t len) {
 char text[192]; assert(strcmp(from,"10000")==0 && len<sizeof(text));
 memcpy(text,data,len);text[len]=0;
 result=run(text,&config,&spy,&response)==F39_RESULT_OK;
}
static void sms(const char *text) {
 sms_ingress_feed_line("+CMT: \"10000\",\"\",\"\"");
 sms_ingress_feed_line(text);sms_ingress_process();
}
int main(void) {
 config=seed();sms_ingress_set_callback(command);
 sms("RELAY,1#");assert(!result && !output_level);
 spy.gps_ok=true;spy.speed=20;
 sms("RELAY,1#");assert(!result && !output_level);
 spy.speed=19.99f;
 sms("RELAY,1#");assert(result && output_level && relay_get());
 sms("RELAY,1#");assert(result && output_level);
 spy.gps_ok=false;
 sms("RELAY,0#");assert(result && !output_level && !relay_get());
 sms("RELAY,0#");assert(result && !output_level);
 spy.gps_ok=true;spy.speed=NAN;
 sms("RELAY,1#");assert(!result && !output_level);
 spy.speed=-1;
 sms("RELAY,1#");assert(!result && !output_level);
 spy.speed=0;
 sms("RELAY,1,extra#");assert(!result && !output_level);
 sms("RELAY,2#");assert(!result && !output_level);
 sms("RELAY,1#");assert(result && output_level);
 sms("RELAY,0,extra#");assert(!result && output_level);
 sms("RELAY,0#");assert(result && !output_level);
 return 0;
}
'''

def main():
    source=actions.HARNESS[:actions.HARNESS.index('int main(')]
    source=source.replace('relay_get(', 'fixture_relay_get(').replace('p.relay_get=relay_get;', 'p.relay_get=fixture_relay_get;')
    source=source.replace('s->relay=on;return true;', 's->relay=on;relay_set(on);return true;')
    source='#include "relay.h"\n'+source+MAIN
    with tempfile.TemporaryDirectory(prefix='relay_sms_') as directory:
        t=Path(directory)
        (t/'h.c').write_text(source,encoding='ascii')
        (t/'n32l40x.h').write_text('#include <stdint.h>\n#define GPIOA ((void*)1)\n#define GPIO_PIN_11 2048U\nvoid GPIO_SetBits(void*,unsigned);\nvoid GPIO_ResetBits(void*,unsigned);\n',encoding='ascii')
        modules=['f39_command','f39_reply','f39_config_adapter','terminal_identity','sms_ingress','sms_command','relay']
        subprocess.run([actions.find_compiler(),'-std=c99','-Wall','-Wextra','-Werror','-I',str(t),'-I',str(ROOT/'include'),str(t/'h.c'),*[str(ROOT/'src'/f'{name}.c') for name in modules],'-o',str(t/'h.exe')],check=True)
        subprocess.run([str(t/'h.exe')],check=True)
    print('test_relay_sms: PASS')

if __name__ == '__main__':
    main()
