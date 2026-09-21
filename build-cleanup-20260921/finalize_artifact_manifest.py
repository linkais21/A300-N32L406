from pathlib import Path
import hashlib, json, struct, zlib

d = Path(__file__).resolve().parents[1] / "artifacts/A300-406-V3.071-Cleanup-20260921"
app = (d / "App-N32L406CBL7.bin").read_bytes()
ota = (d / "A300-406-OTA-V3.071.bin").read_bytes()
magic, version, size, crc, product, _ = struct.unpack("<IIIII12s", ota[:32])
assert magic == 0xA300B007 and version == 3071 and size == len(app)
assert ota[32:] == app and crc == zlib.crc32(app) & 0xffffffff
files = {}
for p in sorted(d.iterdir()):
    if p.name == "manifest.json":
        continue
    files[p.name] = {"size": p.stat().st_size,
                     "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
report = {
    "schema_version": 1,
    "product": "T360-A300_406",
    "version": "T360-A300_406_20260920230201,V3.071",
    "mcu": "N32L406CBL7",
    "build_source": "build-cleanup-20260921/after",
    "flash_used": 105816,
    "flash_limit": 106496,
    "flash_remaining": 680,
    "ram_guard": "FAIL_INCOMPLETE_WHOLE_PROGRAM_STACK_EVIDENCE",
    "ota_header": {"magic": "0xA300B007", "version_code": version,
                    "body_size": size, "body_crc32": f"{crc:08x}",
                    "product_id": f"0x{product:08x}"},
    "artifacts": files,
}
(d / "manifest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("artifact manifest and OTA CRC: PASS")
