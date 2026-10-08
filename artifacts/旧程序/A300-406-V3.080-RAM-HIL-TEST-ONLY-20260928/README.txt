V3.080 dedicated-device HIL package; not a production release.
Upload OTA-A300-406-V3080-HIL.bin to the test FOTA platform as model A300-406, version code 3080. The platform supplies the detached signature.
Use one dedicated device; do not start a fleet campaign.
Record complete serial logs for normal OTA, power interruption, network interruption, F39/SMS load, AGNSS injection and repeated post-upgrade HEALTH.
Require every observed F=0 and RAM_GAP>=4096, successful trial/ACTIVE and no unexplained AGNSS ACK-NAK. Match the boot version and App hash to manifest.json before considering production release.
