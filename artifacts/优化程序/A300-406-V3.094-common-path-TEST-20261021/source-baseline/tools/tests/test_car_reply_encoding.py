"""CAR readback must retain GBK across UTF-8 F39 and GBK parameter writes."""
import test_f39_actions as base

MAIN=r'''
int main(void) {
    device_config_t c=seed();spy_t s={0};f39_reply_t r;s.persist_ok=true;
    assert(run("CAR,18B12345",&c,&s,&r)==F39_RESULT_OK);
    assert(run("CAR",&c,&s,&r)==F39_RESULT_OK);
    assert(!strcmp((char*)r.data,"CAR,\xd4\xc1" "B12345=Success!\r\n"));
    strcpy(c.plate_no,"\xd4\xc1" "B12345");
    assert(run("CAR",&c,&s,&r)==F39_RESULT_OK);
    assert(!strcmp((char*)r.data,"CAR,\xd4\xc1" "B12345=Success!\r\n"));
    return 0;
}
'''
if __name__=='__main__':
    # Independent Python codecs verify all documented numeric province codes.
    provinces = '京浙津皖沪闽渝赣港鲁澳豫蒙鄂新湘宁粤藏琼桂川蜀冀贵黔晋云滇辽陕秦吉甘陇黑青苏台'
    checks = []
    for code, province in enumerate(provinces, 1):
        expected = b'CAR,' + province.encode('gbk') + b'B12345=Success!\r\n'
        literal = ''.join('\\x%02x' % byte for byte in expected)
        checks += [
            f'assert(run("CAR,{code:02d}B12345",&c,&s,&r)==F39_RESULT_OK);',
            'assert(run("CAR",&c,&s,&r)==F39_RESULT_OK);',
            f'assert(!strcmp((char*)r.data,"{literal}"));',
        ]
    MAIN = MAIN.replace('    return 0;', '\n'.join(checks) + '\n    return 0;')
    base.HARNESS=base.HARNESS.replace('int main(void)','int original_main(void)')+MAIN
    raise SystemExit(base.main())
