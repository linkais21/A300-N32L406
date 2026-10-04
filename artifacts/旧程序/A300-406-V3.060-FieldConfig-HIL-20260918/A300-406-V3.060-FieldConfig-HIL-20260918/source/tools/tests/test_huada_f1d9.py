def checksum(f):
 c1=c2=0
 for b in f[2:-2]: c1=(c1+b)&255; c2=(c2+c1)&255
 return c1,c2
def frame(p=b'abc'):
 f=bytearray(b'\xf1\xd9\x0b\x10'+len(p).to_bytes(2,'little')+p+b'\0\0'); f[-2:]=bytes(checksum(f)); return bytes(f)
def test_huada_frames():
 f=frame(); assert checksum(f)==tuple(f[-2:]); assert int.from_bytes(f[4:6],'little')+8==len(f); assert int.from_bytes(f[:-1][4:6],'little')+8!=len(f)-1
if __name__=='__main__': test_huada_frames(); print('test_huada_f1d9: PASS')
