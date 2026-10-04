import contextlib, io, pathlib, shutil, sys, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[2]
WORK=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'tools/tests'))
import test_fota_platform_flow as flow
with tempfile.TemporaryDirectory(prefix='ota_success_red_') as directory:
    root=pathlib.Path(directory)
    for folder in ['src','include','bootloader/include']:
        shutil.copytree(WORK/'source'/folder,root/folder)
    for name in ['src/fota.c','src/fota_checkpoint.c','include/fota_checkpoint.h']:
        shutil.copy2(WORK/'before'/name,root/name)
    flow.ROOT=root
    source=flow.HARNESS+r'''
int main(void) {
    fresh();seed_bcr(BCR_ACTIVE);
    bcr_record_t *b=(bcr_record_t*)(flash+BCR_SLOT_A_ADDR);
    b->image_version=FW_VERSION_COUNTER;b->transaction_length=4268;
    b->crc32=crc32_compute(b,offsetof(bcr_record_t,crc32));
    fota_checkpoint_t c={0};c.version=FW_VERSION_COUNTER;c.expected_length=4300;c.offset=4096;
    strcpy(c.url,"http://fota.lhhn.net/d/task-token-123?d=12345678901");
    flash_owner=EXT_FLASH_OWNER_OTA;assert(fota_checkpoint_commit(&c));flash_owner=0;
    pump(2);tcp=TCP_STATE_OPEN;pump(1);
    assert(strstr(request,"POST /api/device/updates/progress"));
    return 0;
}
'''
    try:
        flow.run_flow(source,'before_fix')
    except AssertionError as error:
        assert 'Assertion failed: strstr(request' in str(error),str(error)
        (WORK/'red.log').write_text(str(error),encoding='utf-8')
        print('RED reproduced: pre-fix firmware sends a check GET instead of success POST')
    else:
        raise AssertionError('Pre-fix implementation unexpectedly passed')
