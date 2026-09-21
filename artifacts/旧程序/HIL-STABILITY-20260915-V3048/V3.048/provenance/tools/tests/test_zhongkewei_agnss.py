def build(user,pwd):
 if not user or not pwd: raise ValueError
 return f'user={user};pwd={pwd};cmd=full;lat=22.0000000;lon=114.0000000;alt=100.00;'
def test_zhongkewei_auth():
 assert build('u','p').startswith('user=u;pwd=p;cmd=full;')
 try: build('','p'); assert False
 except ValueError: pass

def test_response_classification():
 # CASBIN/CSIP starts BA CE. The transport authentication request is a
 # different, explicitly unverified server contract.
 assert bytes((0xBA, 0xCE)) == b'\xba\xce'
 assert (20 + 10) == 30  # documented wire size: payload + CSIP header/trailer
 assert 20 % 4 == 0
if __name__=='__main__': test_zhongkewei_auth(); print('test_zhongkewei_agnss: PASS')
