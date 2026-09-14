# RAM-01 follow-up and serial diagnostics

Authorized scope: prioritize RAM-01; investigate FOTA 401 and GNSS drops. ACC switching near 112 minutes was intentional. Preserve current worktree, wire protocols, Flash formats, buffer capacities and 4096-byte margin. No release packaging, flash or deployment.

1. Rebuild current sources into a new baseline directory and collect final LTO evidence. Completed: Flash 105160 B, known main chain 2984 B, main frame 792 B, FOTA frame 1208 B.
2. Add an artifact-based regression requiring the known main chain to fit available RAM minus the existing 4096-byte margin. This is a necessary condition, not whole-program acceptance. Run against baseline and record RED.
3. Preserve function boundaries for large mutually exclusive command/request work so local arrays do not remain in parent frames. Prefer this to new static buffers (consume shared SRAM) or global compiler switches (broad timing/size impact). Compare actual ELF/MAP and host protocol tests. Retain only measured improvements.
4. Reproduce GNSS software queue saturation and overlength paths using actual gps.c with hardware stubs. Add diagnostic cause counters and hardware overrun observation without changing capacity or inventing a field root cause. Validate reset/counter behavior and existing GNSS tests. Hardware attribution requires a new capture.
5. Check FOTA using read-only requests without real device identity, local source and contract tests. Do not silently resolve the X-Device-Key versus task-token contract conflict. Direct request reproduced HTTP 401 with gunicorn HTML; deployment origin remains unverified.
6. Run targeted regressions, fresh ARM build and RAM/release gates. Report incomplete stack evidence honestly; no unconditional gate bypass. Update diagnosis with evidence, remaining IRQ/library/indirect-call gaps and HIL requirements.
