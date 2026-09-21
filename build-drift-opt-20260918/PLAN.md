# 406 static report filter optimization / test delivery
Target: A300-406 N32L406; live reports stay anchored while physically stationary, independent of ACC/sleep. Preserve raw GNSS, validation and reset paths, protocol and Flash layout.
1. Reproduce zero-speed noisy sensor and isolated spikes using actual C module. Synthetic evidence is not a replay of missing 200 ms hardware samples.
2. Three-sample median then fixed-point low-pass acceleration; 5-sample filtered span retains 30/60 mg hysteresis. Isolated instability pauses candidate evidence for at most 2 s; continuous instability resets. Continuous credible motion releases; failures invalidate immediately. Fixed storage, no heap or new I/O.
3. Test quiet/noisy lock, sustained movement, short jolt, tick wrap, stale/failed sensors, duplicate RMC, reset, actual JT808 dual-channel payload. Review diff and preserve existing modifications.
4. Audit 406 historical release identity/OTA header and reachable platform records, reserve a fresh identity before target build. G452 V1 registry is a different product lineage; do not mix into L406 V3 counter.
5. Build and run capacity/security/OTA gates. Deliver SWD and platform-upload OTA only with traceable identical App body, CRC/SHA, provenance and explicit HIL limitations. Do not bypass a failed release gate. No upload/flash/deploy in this task.
Risks: sensor-only filtering may delay start detection; slow uniform movement with zero GNSS speed is unobservable. Measure unlock latency and real creep in HIL. Existing Flash headroom 76 B and incomplete stack gate may block delivery.
