# RAM-01：发布 LTO 栈证据与阻断

2026-09-13。对应 `build/quality-audit-20260912/REPORT.md` 的 RAM-01。
本轮完成度量和误放行修复；运行时安全验收尚未完成。

## 改动与使用

- Makefile 编译和最终链接均保留 `-Os -flto=1 -flto-partition=one`，加入
  `-fstack-usage`。签名包装器和 micro-ecc 继续单独 `-fno-lto`，也生成 `.su`。
- 链接生成 `stack-evidence.json`，记录当前 ELF、MAP、最终 LTO `.su` 和两个
  非 LTO `.su` 的 SHA-256。只读取明确的本次链接输入，不扫描历史 build 目录。
- `make stack-report` 重新反汇编当前 ELF，生成 `stack-analysis.json` 和
  `stack-analysis.disassembly.txt`。证据缺失、损坏或哈希不匹配返回非零；
  完整生成一份标为 `incomplete` 的诊断报告可以返回零，**不代表发布通过**。
- `make ram-guard`、`make stack-guard`、`make release-gate` 消费该报告。
  删除未经证明的固定 `AUDITED_STACK_BYTES=2440`；保留 24,576 B SRAM 和
  4,096 B runtime gap 要求。App 缺少证据、预算不足或证据不完整均失败。
- `tools/build_dev_release.py` 在 App 构建后、Boot 构建与打包前调用同一个
  `release-gate`。现有发布流程在 gate 前仍会保留版本目录并刷新版本头，
  本轮没有运行发布脚本，也没有更改这个已有副作用。
- Boot MAP 检查保留原有 18,040 B 静态 RAM 回归上限；仅声明静态容量通过，
  不再借 App 的 2,440 B 常量声称 Boot 栈安全。

当前没有可接受的完整 runtime budget。因此 App 的 RAM/stack/release gate
会持续阻断；工具没有临时跳过开关或默认宽松值。后续只有在补齐下述证据并实现
经审查的预算验收契约后才能恢复发布，不能仅把 `incomplete` 改成 `passed`。
`make all` 仍允许生成诊断固件，不代表可发布。

首次升级度量配置以及发布/CI 必须 `make -B all`。普通增量构建的一般头文件、
编译参数指纹问题仍属于 BUILD-01；哈希绑定证明报告与产物一致，不证明源文件
和所有历史对象之间的增量依赖已经健全。

## 本轮实际证据

完整构建：`build/ram01-20260913/`。App Flash 105,776 / 106,496 B，
静态 RAM `.data + .bss = 17,820 B`。没有改变 C 源码、链接布局、版本或设备协议。

| 项目 | 栈帧/调用链字节 | 解释 |
|---|---:|---|
| `main` | 792 | 最终 LTO 单帧 |
| `fota_process` | 1,208 | 最终 LTO 单帧；旧非 LTO gate 的 800 B 阈值不适用 |
| 签名包装器 / `uECC_verify` | 24 / 544 | 实际参与链接的两个非 LTO 翻译单元 |
| 审计所列 OTA 四级链 | 2,568 | 792 + 1,208 + 24 + 544，未含 ECC 子调用 |
| OTA 到 ECC 直接子调用 | 2,872 | 延伸到 `uECC_vli_modMult → uECC_vli_mult` |
| 当前已解析主循环最长直接调用帧链 | 2,984 | `main → fota_process → checkpoint_save → newest → ext_flash_read → spi_flash_read → ready → read_status_command` |
| 扣除静态 RAM 和上述帧链后的余额 | 3,772 | 比 4,096 B 要求少 324 B，尚未扣堆与异常等缺口 |

2,984 B 是已知直接调用帧的静态累计估算，不是完整栈上限、实测峰值或已发生
溢出的证明。不同分支的帧使用和可达性尚未做逐指令形式化分析。

解析器保留 GCC clone 类型，只匹配 `.su` 中省略数字 ID 的 `constprop/isra`
和汇编名称中的 `lto_priv` 差异；不借原函数栈帧代替优化 clone。重名 `.su`
取最大值。动态或格式异常的 `.su` 直接拒绝。

当前报告列出 91 个缺少 `.su` 的符号（含运行库、汇编入口/别名）、56 个间接
跳转位置、117 个跨符号尾跳转和 1 条直接调用环。数量是保守诊断，跨符号跳转
可能是汇编内部标签；不能等同于实际执行次数或真实函数数量。尾调用不机械
相加，间接调用不猜测目标；它们全部作为待补证据明确保留。
直接调用环涉及 `at_send_wait → process_deferred_urc_one → process_urc → at_send_wait`，
需要结合可达状态和重入保护进一步证明有限深度；本轮未修改 AT 状态机。

## 自动验证

本机 `make` 不在 PATH，实际使用
`D:/A300_Tools/toolchains/make-4.4.1/bin/make.exe`，以下简称 `make`。

- `make -B all BUILD=build/ram01-20260913`：成功；Flash 告警剩余 720 B。
  增加采集参数使 RES-01 报告标记 `CONFIGURATION_CHANGED`，没有改写冻结基线。
- `make release-gate BUILD=build/ram01-20260913`：release identity 通过；
  RAM gate 非零退出，报告 3,772 < 4,096 和不完整栈证据。这是修复后的预期阻断，
  **不是全部 gate 通过**。
- `python tools/tests/test_lto_stack_guard.py`：覆盖调用链累加、ECC 子帧、
  重名最大值、GCC clone、缺失帧、间接/尾调用、调用环、动态/坏格式、缺失/过期
  ELF/MAP/.su、旧成功报告被失败替换，以及无证据的 MAP 不得误放行。包含 RED→GREEN。
- `python tools/tests/test_fota_stack_guard.py`、`python tools/tests/test_ram_guard.py`：通过。
- `python tools/tests/test_flash_capacity_guard.py`：10 项通过。
- `python tools/tests/test_flash_gate_build.py`：真实 ARM 构建，串行/并行共 8 组缺失
  MAP/profile/栈 manifest/LTO `.su` 恢复场景通过；测试只使用临时目录。
- `python tools/tests/test_feature_guards.py`、`python tools/tests/test_ram_watermark.py`、
  `python tools/tests/test_stack_health_observability.py`：通过。
- 单独运行 `python tools/tests/test_platform_trust_anchor.py` 和
  `python tools/libc_parser_guard.py build/ram01-20260913/a300_firmware.map`：通过；
  因 release-gate 在 RAM 阶段停止，这两项没有依赖其后续目标执行。
- `git diff --check`：通过；独立审查发现的 Boot 静态上限回归已经 RED→GREEN 修复。

使用当前源码和 HEAD 中未加栈采集参数的 Makefile，在独立
`build/ram01-baseline-20260913/` 全量构建对照，两份 BIN 字节完全一致：
`0040323198cc72f198ac3bb57d6133e4b0836f1939e7242300bd9a88755a6241`。
昨天审计 BIN 的哈希不同，不能用历史产物代替本轮同源对照。
本轮 Flash 和静态 RAM 节省均为 0 B，设备执行代码未改变。

## 需要实机/HIL 验证

沿用设备已有 `HEAP_USED / STK_PEAK / RAM_GAP` 健康日志，记录固件 BIN 哈希、
工具链/宏配置、触发步骤、持续时间、最大堆与栈水位和最小 gap。日志脱敏保存。
验收必须覆盖冷启动（含首次填色前的 SystemInit）、OTA 合法/非法签名、断电复位
恢复、短信最长配置事务、最长串口命令、双通道并发 RX、Flash 失败恢复、AGNSS
注入、STOP 唤醒和最高允许 IRQ 嵌套。

同时补齐 ECC 曲线函数指针/回调目标、所链接 libc/libm 的栈证据、尾调用与调用环
的有限深度分析、Cortex-M4 基本/浮点异常帧和对齐及中断软件帧。RAM-02 的堆峰值/
硬边界仍需独立验证。最终按静态 RAM + 完整栈/异常 + 堆峰值 + 4,096 B gap
核对 24,576 B 总容量；水位测试覆盖有限，不能单独替代未测路径的边界证明。

本轮未烧录、未发送设备控制、未部署、未打包、未提交或推送。保留此前 RES-01
工作树改动和原始审计资料。RAM-01 的测量与误放行问题已处理，运行时风险不能关闭。
