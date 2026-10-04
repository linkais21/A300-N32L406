"""Replay the production C success POST into the selected platform's test client."""
import contextlib, hashlib, io, json, pathlib, sys
sys.dont_write_bytecode=True
ROOT=pathlib.Path(__file__).resolve().parents[2]
PLATFORM=pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0,str(PLATFORM.parent))
sys.path.insert(0,str(ROOT/'tools/tests'))
from ota_platform.tests.test_device_protocol import DeviceProtocolTests
from ota_platform.db import open_connection
from test_fota_platform_flow import HARNESS,run_flow

case=DeviceProtocolTests()
case.device_id='12345678901'
case.model='A300-406'
case.version_code=json.loads((ROOT/'release_identity.json').read_text())['firmware_version_counter']
case.setUp()
try:
    checked=case.check_update(currentVersionCode='1').get_json()
    token=checked['downloadToken']
    source=HARNESS+r'''
int main(void) {
    fresh();seed_bcr(BCR_ACTIVE);
    bcr_record_t *b=(bcr_record_t*)(flash+BCR_SLOT_A_ADDR);
    b->image_version=FW_VERSION_COUNTER;b->transaction_length=4268;
    b->crc32=crc32_compute(b,offsetof(bcr_record_t,crc32));
    fota_checkpoint_t c={0};c.version=FW_VERSION_COUNTER;c.expected_length=4300;c.offset=4096;
    strcpy(c.url,"http://fota.lhhn.net/d/__TOKEN__?d=12345678901");
    flash_owner=EXT_FLASH_OWNER_OTA;assert(fota_checkpoint_commit(&c));flash_owner=0;
    pump(2);tcp=TCP_STATE_OPEN;pump(1);assert(strstr(request,"POST "));
    for(unsigned i=0;request[i];i++)printf("%02x",(unsigned char)request[i]);
    return 0;
}
'''
    capture=io.StringIO()
    with contextlib.redirect_stdout(capture):
        run_flow(source.replace('__TOKEN__',token),'platform_wire')
    raw=bytes.fromhex(capture.getvalue().strip()).decode().replace('\r\n','\n')
    head,body=raw.split('\n\n',1);body=body.rstrip('\n')
    lines=head.splitlines();headers=dict(line.split(': ',1) for line in lines[1:])
    assert int(headers['Content-Length'])==len(body.encode())
    assert json.loads(body)['state']=='success'
    response=case.client.post(lines[0].split()[1],data=body,headers=headers)
    assert response.status_code==201,response.status_code
    db=open_connection(case.database_path)
    row=db.execute('SELECT state,version_code,progress FROM device_upgrade_events ORDER BY id DESC LIMIT 1').fetchone()
    assert tuple(row)==('success',case.version_code,100)
    # Expired tokens must be rejected by the unchanged server.
    db.execute("UPDATE device_download_tokens SET expires_at='2000-01-01T00:00:00+00:00'")
    db.commit();db.close()
    response=case.client.post(lines[0].split()[1],data=body,headers=headers)
    assert response.status_code==401
    result=dict(production_c_post='accepted 201; stored success',expired_token='rejected 401',
                platform_sources={n:hashlib.sha256((PLATFORM/n).read_bytes()).hexdigest()
                                  for n in ('routes_device.py','services.py','db.py')})
    print(json.dumps(result,indent=2))
finally:
    case.tearDown()
