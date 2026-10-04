"""Replay a real signed OTA file through production App and Bootloader verifiers.

Explicit file inputs keep immutable release binaries out of source fixtures.
Only modem and NOR hardware are simulated; signature verification is real.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

from test_fota_platform_flow import HARNESS, run_flow


def replay(package_path, metadata_path):
    package = package_path.read_bytes()
    metadata = json.loads(metadata_path.read_text())
    assert len(package) == metadata["size"]
    assert hashlib.sha256(package).hexdigest() == metadata["sha256"]
    signature = bytes.fromhex(metadata["signature"])
    assert len(signature) == 64
    # Remove only the existing verifier double; link the shipped implementation.
    harness, removed = re.subn(
        r"bool firmware_signature_verify\([^\n]+\)\{.*?\n\}", "", HARNESS,
        count=1, flags=re.S)
    assert removed == 1
    # Capture the full 100 KiB transfer's progress output for failure assertions.
    harness = harness.replace("logs[2048]", "logs[8192]")
    code = r'''
#include "bootloader/include/image_verify.h"
static const uint8_t package[]={__PACKAGE__};
static const uint8_t digest[32]={__DIGEST__};
static const uint8_t signature[64]={__SIGNATURE__};
bool boot_ext_read(uint32_t address, void *out, uint32_t n){
    assert(address<=sizeof flash && n<=sizeof flash-address);
    memcpy(out,flash+address,n);return true;
}
bool boot_ext_is_complete(uint32_t address,uint32_t n){return address==0x10000 && n==sizeof package;}
bool boot_rollback_counter(uint32_t *out){*out=0;return true;}
void boot_watchdog_feed(void){}
int main(void){
    for(unsigned tamper=0;tamper<3;tamper++){
        fresh();
        uint8_t sig[64];memcpy(sig,signature,64);if(tamper==1)sig[0]^=1;
        fota_request_t req={"http://fota.lhhn.net/fw?token=task-token-123",
                           sizeof package,NULL,__VERSION__,digest,sig,__KEY_ID__};
        assert(fota_start_request(&req)==0);
        for(unsigned i=0;i<160 && !opens;i++)pump(1);
        assert(opens==1);tcp=TCP_STATE_OPEN;pump(1);assert(sends==1);
        char header[100];snprintf(header,sizeof header,
            "HTTP/1.1 200 OK\r\nContent-Length: %u\r\n\r\n",(unsigned)sizeof package);
        bytes(header,strlen(header));
        for(size_t offset=0;offset<sizeof package;offset+=256){
            size_t n=sizeof package-offset;if(n>256)n=256;
            uint8_t chunk[256];memcpy(chunk,package+offset,n);
            if(tamper==2 && offset==256)chunk[0]^=1;
            bytes(chunk,n);
        }
        pump(2);
        if(tamper){
            assert(fota_get_state()==FOTA_STATE_ERROR && !resets);
            assert(!flash_owner && !workspace_owner && !bcr_read_verified);
            assert(strstr(logs,tamper==1?"stage=signature":"stage=sha256"));
            continue;
        }
        assert(fota_get_state()==FOTA_STATE_READY && bcr_read_verified);
        image_manifest_t manifest;memcpy(&manifest,flash+0x10000,sizeof manifest);
        assert(verify_candidate(&manifest)==IMAGE_VERIFY_OK);
        flash[0x10000+256]^=1;
        assert(verify_candidate(&manifest)==IMAGE_VERIFY_HASH);
        flash[0x10000+256]^=1;
        g_tick_ms+=15000;pump(1);assert(resets==1);
    }
    puts("real platform OTA: App authorization + BCR + Bootloader signature/hash + tamper rejection + bounded reset PASS");
    return 0;
}
'''
    for key, value in {"__PACKAGE__": package, "__DIGEST__": bytes.fromhex(metadata["sha256"]),
                       "__SIGNATURE__": signature}.items():
        code = code.replace(key, ",".join(str(b) for b in value))
    code = code.replace("__VERSION__", str(metadata["versionCode"]))
    code = code.replace("__KEY_ID__", str(metadata["signingKeyId"]))
    run_flow(harness + code, "real_platform_ota", real_crypto=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()
    replay(args.package, args.metadata)
