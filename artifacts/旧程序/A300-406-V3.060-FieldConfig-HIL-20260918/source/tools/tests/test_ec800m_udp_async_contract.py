from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
def run():
    h = (ROOT/'include'/'ec800m.h').read_text()
    c = (ROOT/'src'/'ec800m.c').read_text(encoding='utf-8', errors='ignore')
    for t in ('ec800m_udp_txn_start','ec800m_udp_txn_process','ec800m_udp_txn_result'):
        assert t in h and t in c
    assert 'UDP_TXN_OPEN' in c and 'UDP_TXN_SEND' in c and 'UDP_TXN_CLOSE' in c
    cfg = (ROOT/'src'/'cfg_query.c').read_text(encoding='utf-8', errors='ignore')
    assert 'ec800m_udp_txn_start' in cfg and 'ec800m_udp_txn_process' in cfg
    print('ec800m udp async contract: PASS')
if __name__ == '__main__': run()
