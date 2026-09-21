# micro-ecc provenance

- Upstream: `https://github.com/kmackay/micro-ecc`
- Commit: `d037ec89546fad14b5c4d5456c2e23a71e554966`
- License: BSD-2-Clause (`LICENSE.txt`)
- Recovery source: locally retained A300 import plus its complete reverse patch;
  the reverse patch applied with zero conflicts to restore the upstream files.
- Local arithmetic changes: none.

SHA-256:

- `uECC.c`: `a13ea714b1db5fc0f021ea4105caf8d196954af180882b8ad9f293d33760dd05`
- `uECC.h`: `9751a22d3fb9b11daab405c4a7d4702a4d9969b3785eaff602ed19b108e97a3f`
- `curve-specific.inc`: `9e9d8d6771731dce2e084a4469d0dd2e9ac6245c8773766198a83f82d24b6313`
- `platform-specific.inc`: `af1ef1ccb0b253b5d20e6080678514782c562d5bf909ce9a67dde73e50da605a`
- `types.h`: `61bd255c0dca4c69dfc779cc5c1fe1cbff47039d4bb7f37578a88f63b7fca466`
- `uECC_vli.h`: `a8ff7957855e6520674cad4bcaf8f3e752d40f6c3f7501915c3504c777be1e7a`
- `LICENSE.txt`: `ffd8b033d2df7568c25a98866bd92b1656f7da82d7f813c0b2eb85ec36611193`

Firmware builds enable only `uECC_SUPPORTS_secp256r1=1` and disable the other
curves and compressed points. Only verification is referenced by product code;
signing and key generation are not exposed by the A300 wrapper.
The build selects `uECC_PLATFORM=uECC_arch_other`, the upstream portable-C
backend, because the retained upstream source set does not include optional
`asm_arm.inc`; no algorithm source is changed.
