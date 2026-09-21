from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def run():
    h = (ROOT / 'include' / 'cfg_query.h').read_text(encoding='utf-8')
    c = (ROOT / 'src' / 'cfg_query.c').read_text(encoding='utf-8')
    assert '39.108.211.33' in h and '10004' in h
    for token in ('cfg_query_init', 'cfg_query_process', 'cfg_query_start',
                  'cfg_query_is_busy', 'cfg_query_take_result'):
        assert token in h and token in c
    assert 'service_workspace_try_acquire' in c
    assert 'ec800m_udp_txn' in c
    assert '0x66U' in c and '0x13U' in c and '0x14U' in c and '0x0dU' in c
    assert 'cfg_query_parse_92' in c
    assert 'at_config_execute_text_command' in c
    mk = (ROOT / 'Makefile').read_text(encoding='utf-8')
    assert 'src/cfg_query.c' in mk
    print('cfg query contract: PASS')

if __name__ == '__main__': run()
