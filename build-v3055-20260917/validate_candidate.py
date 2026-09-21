from pathlib import Path
import json, os, subprocess, sys, time

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(__file__).resolve().parent
LOG = WORK / 'validation'
LOG.mkdir(exist_ok=True)
results = []
tests = '''at_config_serial_f39 at_config_handoff f39_parser f39_config f39_dualset f39_actions f39_end_to_end
gps_huada_output gps_huada_gsv production_test production_gnss nmea_replay gps_drop_diagnostics gps_tx_bounded gps_ntp_apply
production_adc production_relay relay_sms remote_relay feature_guards log_platform_wire log_platform_contract
build_version_refresh release_identity_contract terminal_identity jt808_dual_session jt808_params jt808_params_wire
blind_zone_store blind_zone_replay blind_zone_ack_channel corner_blind_zone_replay ext_flash_layout ext_flash_store_host
fota_active fota_verify_scan fota_resume fota_package fota_check_parser fota_checkpoint_powercut fota_platform_flow
a300_ota_image firmware_signature platform_trust_anchor bootloader_factory_init bootloader_powercut
bootloader_lkg_powercut_c bootloader_bcr_failclosed bootloader_legacy_recovery bootloader_invalid_vector_recovery
boot_cold_start_recovery boot_bcr_device_gate boot_spi_timing boot_flash_probe_retry bootloader_platform_contract
flash_config_v3 flash_config_migration internal_flash_layout service_workspace_contract mileage_quantization
mileage_persistence i2c_accel_vibration_filter i2c_accel_vibration_adapter status_led'''.split()
os.chdir(ROOT)
os.environ['A300_V150_WIRE'] = str(WORK / 'console-wire.txt')
for name in tests:
    cmd = [sys.executable, 'tools/tests/test_' + name + '.py']
    started = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=240)
        output, code = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        output, code = (e.stdout or b'') + (e.stderr or b'') + b'\nTIMEOUT', 124
    (LOG / (name + '.log')).write_bytes(output)
    results.append(dict(name=name, command=cmd, exit_code=code, seconds=round(time.monotonic()-started, 2)))
    (LOG / 'host-results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(name, code, flush=True)
sys.exit(1 if any(r['exit_code'] for r in results) else 0)
