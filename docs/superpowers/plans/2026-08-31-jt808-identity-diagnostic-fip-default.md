# A300_406 JT808 Identity Diagnostic and FIP Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复空 PID 首次持久化导致的 JT808 身份门控失败，增加开机一次完整身份/服务器日志，并让新配置的副服务器默认关闭且升级保留已有 FIP。

**Architecture:** 保持 `ec800m → terminal_identity → flash_config → jt808` 与 `F39 → flash_config → tcp_manager` 分层；为配置写入增加小缓冲分块和失败阶段，在主循环侧只编排诊断。配置 v3 格式、双槽事务和 JT808-2013 身份规则保持不变。

**Tech Stack:** C99、ARM GNU Toolchain、N32L40x SPL、Python host-C harness、Make、BY25Q16 NOR Flash。

## Global Constraints

- 已有非空 FIP 升级后一律保留，不按地址值判断来源。
- 新机、无有效配置和恢复出厂默认 `backup_ip=""/backup_port=0`。
- 完整 IMEI、ICCID、设备 ID、JT808 终端 ID 和服务器只在每次开机打印一次。
- PID 必须在首次 JT808 帧发送前成功持久化。
- v3 Flash 布局、CRC、generation 和最后 commit marker 不变。
- 所有重试有界，无动态分配，不在 ISR 写 Flash。
- 不提交、不推送、不烧录、不部署。

---

### Task 1: 建立身份失败阶段与低栈写入回归

**Files:**
- Modify: `include/flash_config.h`
- Modify: `src/flash_config.c`
- Modify: `include/terminal_identity.h`
- Modify: `src/terminal_identity.c`
- Modify: `tools/tests/test_terminal_identity.py`
- Modify: `tools/tests/test_flash_config_v3.py`

**Interfaces:**
- Produces: `cfg_store_result_t cfg_store_candidate_result(const device_config_t *candidate)`
- Produces: `terminal_identity_result_t terminal_identity_sync_result(char pid[12], char phone[13], char terminal_id[8], bool *derived)`
- Existing bool APIs remain compatibility wrappers.

- [ ] **Step 1: Write RED host-C tests** proving valid IMEI reports persistence-stage failures separately, no JT808 frame is sent on failure, and the real v3 write path uses bounded scratch storage while preserving all power-cut outcomes.
- [ ] **Step 2: Run** `python tools/tests/test_terminal_identity.py` and `python tools/tests/test_flash_config_v3.py`; expect the new result APIs/stack contract assertions to fail.
- [ ] **Step 3: Implement minimal result enums and low-stack v3 streaming write/verify** without changing the on-flash byte format or commit order.
- [ ] **Step 4: Re-run both tests**; expect PASS with `-Wall -Wextra -Werror`.

### Task 2: 默认关闭副服务器并保留已有 FIP

**Files:**
- Modify: `src/flash_config.c`
- Modify: `src/tcp_manager.c`
- Modify: `src/main.c`
- Modify: `src/at_config.c`
- Modify: `tools/tests/test_flash_config_migration.py`
- Modify: `tools/tests/test_f39_config.py`
- Modify: `tools/tests/test_f39_end_to_end.py`
- Create: `tools/tests/test_tcp_manager_fip.py`

**Interfaces:**
- `backup_ip[0]=='\0' || backup_port==0` means CH3 disabled.
- `FIP,<host>,<port>` persists exact endpoint and reconnects.
- `FIP,0` persists empty endpoint and closes CH3.

- [ ] **Step 1: Write RED tests** for empty new default, v1/v2/v3 non-empty FIP preservation, CH3 disabled with empty host or zero port, and no backup fallback to main endpoint.
- [ ] **Step 2: Run new and existing F39/config tests**; expect default/fallback assertions to fail.
- [ ] **Step 3: Set only new defaults to empty/zero and remove main-endpoint fallback** from startup and F39 reconnect; make `tcp_manager` disable zero-port endpoints.
- [ ] **Step 4: Re-run config, F39 and TCP-manager tests**; expect PASS.

### Task 3: 开机一次身份与服务器诊断

**Files:**
- Modify: `src/ec800m.c`
- Modify: `src/jt808.c`
- Modify: `src/main.c`
- Modify: `tools/tests/test_ec800m_health_observability.py`
- Create: `tools/tests/test_startup_identity_log.py`

**Interfaces:**
- Startup output includes one `[DEVICE]` line and one `[SERVER]` line after identity is available.
- Failure output names one of `IMEI_FORMAT/PID_FORMAT/FLASH_LOCK/FLASH_WRITE/VERIFY` and follows the existing 5-second limiter.

- [ ] **Step 1: Write RED behavioral harness** capturing `dbg_printf` and asserting exact values, single-print behavior, CONFIG/IMEI source, BACKUP=OFF/configured output, and failure reason.
- [ ] **Step 2: Run the harness**; expect missing startup lines and generic `identity invalid` failure.
- [ ] **Step 3: Implement a one-shot boot diagnostic state** driven after EC800M identity readiness and successful identity sync; do not log auth codes.
- [ ] **Step 4: Re-run diagnostics and JT808 session tests**; expect PASS.

### Task 4: 完整回归与构建门禁

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document** startup identity diagnostics, FIP default OFF, `FIP,<host>,<port>` enable and `FIP,0` disable semantics.
- [ ] **Step 2: Run targeted tests** for terminal identity, flash v3/migration, F39, TCP manager, EC800M, dual JT808 sessions and first location.
- [ ] **Step 3: Run** `make all`, `make release-guard`, `make ram-guard`, and `make all EXTRA_CFLAGS=-DA300_HARDWARE_BRINGUP` using the known absolute Make path.
- [ ] **Step 4: Run** `git diff --check`, inspect scoped diff and sensitive logs, and report software verification separately from required HIL verification.
