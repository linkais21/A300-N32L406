# 无效调度与兼容接口清理（2026-09-18）

依据工作区《项目架构与功能清单-2026-09-18》3.1，仅实施已经确认无业务用途的删除项。基于当前未提交工作树，不以 Git HEAD 或历史固件作为对比基线。

## 本轮改动

- `src/main.c`、`src/geofence.c`、`include/geofence.h`：删除围栏空初始化、空周期函数、主循环调用及无效阶段标记；保留 `0x8604` 的失败应答。
- `src/power_mgr.c`、`include/power_mgr.h`：删除无调用的 `pwr_process`、`pwr_get_state`、`pwr_request_sleep` 及专用状态类型；保留初始化、唤醒路由和 ISR。
- `include/reset_diag.h`：注明围栏阶段值为历史诊断保留值，不重编号。
- `tools/tests/test_feature_guards.py`：禁止已删除接口重新进入发布输入。
- `tools/tests/test_geofence_rejection.py`：编译真实围栏拒绝实现，验证空消息、重复调用、流水号边界及发送失败不重试。
- `tools/release_guard.py`：复核后更新主函数身份消费者指纹。内存中仅恢复本轮删除的三条主函数语句，即可与原指纹完全一致；身份处理未改动，指纹检查未放宽。
- 本文为实施和验证记录。

日志裁剪、历史 GNSS 类型、关闭的低功耗分支和安全/恢复功能未改动。当前 `build_all.ps1` 已是 Makefile 包装入口，与原审核文档中的旧脚本描述不同，本轮不删除。未更改版本，不提交、不烧录、不覆盖原构建或交付固件。

## 体积对比

工具链：ARM GNU 14.3.rel1；使用当前 Makefile，同一版本头、相同参数，全新独立输出目录。

| 项目 | 清理前 | 清理后 |
|---|---:|---:|
| App Flash 占用（BIN） | 106380 B | 106372 B |
| 104 KiB App 分区余量 | 116 B | 124 B |
| RAM 静态占用（RAM guard 口径） | 17716 B | 17716 B |
| 已知主调用链栈帧和 | 2536 B | 2536 B |

实际仅释放 **8 B**。空函数和未引用 API 已受 LTO/未引用段回收优化，删除源码不等于大幅减少 Flash。Flash guard 通过容量限制，但仍报告 LOW_HEADROOM；CONFIGURATION_CHANGED 是相对其历史参考基线，不是本轮前后配置不一致。

BIN SHA256：

- 前：`eb75a0568660a8a89ee6e57cb5f24aa14b18f6a0c4a39288594fd7259be6654a`
- 后：`6527758a43a3e62957ee7e70c55d1a6e2a5e6414c1421632fe9f42f36082cea6`

## 验证

在固件仓库运行，`make` 使用工作区 `tools/w64devkit/w64devkit/bin/make.exe`。`-o include/build_version.h` 固定已有版本头，避免时间戳影响前后对比。

```text
make BUILD=build/cleanup-20260918-before -o include/build_version.h all
make BUILD=build/cleanup-20260918-after -o include/build_version.h all
make BUILD=build/cleanup-20260918-after release-gate
make BUILD=build/cleanup-20260918-after ram-guard stack-guard platform-trust-guard
make BUILD=build/cleanup-20260918-after release-guard platform-trust-guard
python tools/libc_parser_guard.py build/cleanup-20260918-after/a300_firmware.map
```

前后构建、Flash 容量检查通过。新增删除约束先在旧代码上失败于 `geofence_init` 残留，修改后通过；拒绝应答测试修改前后均通过（行为保持）。以下定向脚本通过：

```text
test_feature_guards.py
test_geofence_rejection.py
test_work_mode_contract.py
test_shallow_sleep_contract.py
test_acc_stop1_contract.py
test_reset_diag.py
test_release_identity_contract.py
test_terminal_identity.py
```

首次完整门禁停在主函数身份指纹；复核并更新后，单独 `release-guard`、平台信任锚（含篡改拒绝和 32/64 位）及 libc parser guard 通过。

**完整 release gate 未通过。** RAM guard 拒绝不完整的全程序栈证据：缺少 73 个帧、56 个间接转移、131 个尾转移、1 个环。保留清理前构建输入并用 `-o` 排除本轮源码更新时间后，清理前 RAM guard 同样失败，数字完全一致，属于本轮开始前已有的证据缺口；未削弱门禁。日志在 `build/cleanup-20260918-*.log`，前后栈报告位于各自构建目录。

硬件行为需要实机/HIL 验证，本轮未进行。这里的产物仅用于比较，不是发布验收通过的交付包。

## 接手代码的复用边界

现有 N32L406 源码、对应 SDK 和依赖可以作为继续开发的基线，本次就是基于它们重新构建；不能据本次定向测试宣称全部功能已验证。历史 N32G452 源码不直接混入当前发布。

旧 `.o` 和库仅在源码、头文件、配置、工具链与 ABI 一致时才可增量复用；交接基线优先独立目录全量重建。当前 Makefile 已跟踪依赖文件和构建配置指纹，但旧工程目录中的缓存不作为可信交付依据。

历史 BIN/HEX/OTA 包保留为对照或经确认的回退版本，复用前需匹配硬件、Flash 布局、Boot/App 契约、版本及签名/配置兼容，并有对应验证证据。
