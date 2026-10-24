# V3.092 stationary mileage test delivery

1. Preserve current edits; advance only the reviewed release identity to V3.092 / 3092 and synchronize its contract tests and canonical identity fingerprints.
2. Build App and Bootloader with the current production Makefiles, require release and memory gates, and record the final source/version identity.
3. Run stationary mileage, GNSS/JT808, persistent mileage, OTA transport/signature, boot recovery and related release regressions against the final input.
4. Generate new Combined HEX/BIN and OTA files without overwriting previous releases; verify HEX roundtrip/address bounds, vectors, factory-init record, CRC, version, signature trust and exact App payload equality.
5. Include readable test instructions, matching-image HIL checklist, diagnostics and SHA256 manifests; produce and verify a ZIP. No hardware flashing, upload, deployment, commit or push is part of this task.
