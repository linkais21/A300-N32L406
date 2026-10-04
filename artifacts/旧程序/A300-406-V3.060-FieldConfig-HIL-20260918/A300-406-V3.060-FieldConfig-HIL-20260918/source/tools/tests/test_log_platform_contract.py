from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def run():
    h = (ROOT / 'include' / 'log_platform.h').read_text(encoding='utf-8')
    c = (ROOT / 'src' / 'log_platform.c').read_text(encoding='utf-8')
    assert '39.108.211.33' in h and '10009' in h
    for token in ('log_platform_init', 'log_platform_process',
                  'log_platform_on_first_online',
                  'log_platform_on_blind_zone_uploaded'):
        assert token in h and token in c
    assert 'service_workspace_try_acquire' in c
    assert 'work_mode_sleep_is_in_stop1' in c
    assert 'fota_get_state' in c
    assert 'jt808_is_online' in c
    assert 'ec800m_get_csq() < 6' in c
    assert 'ec800m_udp_send_once' in c
    for field in ('*U:', '*R:', '*C:', '*3G:', '*3I:', '*3L:', '*3T:',
                  '*3W:', '*3X:', '*4C:', '*4F:', '*62:', '*6F:', '*74:'):
        assert field in c, field
    mk = (ROOT / 'Makefile').read_text(encoding='utf-8')
    assert 'src/log_platform.c' in mk
    print('log platform contract: PASS')

if __name__ == '__main__': run()
