# A300-406 RAM/stack release closure

## Goal and current evidence

Deliver a new production App and OTA package only after the exact final ELF
passes a complete SRAM/heap/stack/exception budget, host regressions pass, and
the same packaged image passes HIL. Preserve the 4096-byte runtime gap and the
1024-byte hard heap reservation. Keep V3.078 as the existing production image;
V3.079 remains test-only until its own release criteria are met.

The 2026-09-28 review build reports 15980 bytes static SRAM, 2136 bytes on the
longest currently resolved main call chain, 1024 bytes of hard heap, and 5432
bytes remaining before unknown calls and exception costs. The allowance above
the required 4096-byte gap is only 1336 bytes. The main root has 29 unresolved
indirect calls and one internal library call; startup and IRQ roots still have
missing frames. Flash uses 105252/106496 bytes, leaving 1244 bytes. The
existing V3.079 serial capture has a 6212-byte measured gap and no RAM fault,
but it is a different image and is not a worst-case bound.

## Implementation

1. Replace production-only service callbacks with direct, typed calls while
   preserving the host-injected interfaces and all validation and failure
   behavior. First close the 13 F39 calls (`f39_apply_effects`,
   `f39_execute_deferred`, `execute_config`), then the five `at_config` calls,
   and the three service/SMS/EC800M calls. For each group, add a final-ELF
   regression that fails on the current indirect call and passes only when the
   relevant machine-code sites are direct. Exercise both production and host
   bindings with success, missing-service, rejected-command, and retry cases.
   Check Flash size and longest call chain after each group; discard a change
   that only hides a call from the analyzer.

2. Resolve the two micro-ecc indirect calls from the configured secp256r1
   curve using final-ELF target and write-path evidence, or a direct-call
   specialization of the vendored library. Do not modify signature acceptance
   or key handling. Test valid, invalid, malformed, and interrupted FOTA
   signatures against the existing verifier contract.

3. Resolve six newlib `printf` transfers. First inspect the exact linked
   formatter and its reachable target tables. Prefer verified target-set
   evidence from the final ELF; replace the formatter only if that proof cannot
   be made sound and a bounded replacement fits the 1244-byte Flash headroom.
   Preserve format output and truncation/error behavior in host tests.

4. Complete final-link frame proof for startup, the `__aeabi_dmul` internal
   call, every enabled IRQ, HardFault, and FPU extended/lazy exception frames.
   Derive maximum preemption depth from the actual NVIC priorities and ARM
   exception rules; include alignment and fault entry. Reject unknown targets,
   cycles, and missing frames. Do not treat a measured watermark as an upper
   bound. Add negative tests where a new indirect call, unknown IRQ frame, or
   changed compiler configuration makes the gate fail.

5. Compute the reviewed worst-case budget from the final MAP and call graph:
   static SRAM + linker alignment + hard heap + maximum boot/main stack +
   maximum nested exception stack + 4096 <= 24576. If it fails, reduce actual
   static buffers or split a measured call chain, then repeat steps 1-4. Replace
   the unconditional App rejection in `map_ram_guard.py` only when the complete
   hash-bound evidence and budget above can be checked automatically.

6. Run focused host tests, `make all`, `make release-gate`, and `git diff --check`
   on the final source. Assign the next version and build the App and OTA image
   from that exact source. Record source, ELF, MAP, App, and OTA hashes. On one
   dedicated device verify normal OTA, power and network interruption/recovery,
   F39/SMS load, AGNSS injection, and post-upgrade health. Require every
   observed `F=0` and `RAM_GAP>=4096`; investigate any AGNSS ACK-NAK. Package
   production artifacts only after the matching-image HIL results pass.

## Stop conditions

- `stack-analysis.json` has any reachable unknown frame, indirect target,
  unresolved internal/tail transfer, or cycle: no production package.
- The complete static budget leaves less than 4096 bytes, Flash exceeds 106496
  bytes, or a host/security test fails: revise code and rebuild.
- The exact packaged image has no matching HIL evidence or reports a RAM fault,
  insufficient gap, OTA failure, or unexplained AGNSS rejection: retain it as
  test-only and diagnose before production delivery.
