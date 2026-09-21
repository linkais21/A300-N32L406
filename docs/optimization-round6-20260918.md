# 第六轮保持功能优化：跳表目标证据（2026-09-18）

本轮将第五轮列出的 11 处跳表转换为可重复的局部目标审计：115 个表项、195 字节均与最终 BIN 对应字节一致，所有已解码目标均落在原函数的指令边界。本轮没有 Flash/RAM 体积收益，也没有完成全程序 RAM 证明；发布门禁仍拒绝，需要第七轮继续闭合证据。

## 实际改动

- `tools/stack_usage_guard.py`：新增 `table_target_evidence`。识别紧邻的同寄存器 CMP + 无符号 BHI 与 PC 相对 TBB/TBH，记录比较点、默认目标、索引上界、原始表字节、逐项目标/所属函数及可见的绕过比较入口。缺失字节、非 PC 基址、错误寄存器、非指令目标、未知范围、超过审计容量等均保留明确拒绝原因。解码出的跨函数目标只增加调用图可达性，不给予栈释放或完整性信用。
- `tools/tests/test_stack_table_targets.py`：6 个测试方法，含多组拒绝子用例；覆盖跨函数后继帧/缺口传播、TBH 半字对齐、重复目标、表字节变化、错误/损坏表、直接跳入范围检查之后、CBZ 旁路和 literal 地址注释不误报。
- `docs/superpowers/plans/2026-09-18-preserve-features-round6.md`、本文：计划、结果和后续范围。
- `build/optimization-round6-20260918/`：分析器起始快照、输入/最终哈希、RED 日志、验证脚本、命令退出码/日志、独立最终构建、`table-audit.json` 及 73 个缺失帧的最终代码清单 `missing-frame-inventory.json`。该清单不推断库帧数值。

本轮既有输入仅改变栈分析工具；固件 C 源码、版本、构建参数及交付包没有修改。保留工作树中的所有已有修改，未提交、推送、部署或烧录。

## 最终链接结果

| 项目 | 第五轮 | 第六轮 |
|---|---:|---:|
| App Flash / BIN | 106292 B | 106292 B |
| App 分区余量 | 204 B | 204 B |
| 静态 RAM | 17716 B | 17716 B |
| main 已知帧和（非上限） | 2536 B | 2536 B |
| 全局缺失帧 | 73 | 73 |
| 全局未解决间接转移 | 67 | 67 |
| 未证明尾转移 / 调用环 | 131 / 1 | 131 / 1 |
| 自动解码并核对 BIN 的跳表 | 0 | 11 |

最终 ELF 与 BIN 均与第五轮逐字节对应身份一致：

- ELF SHA256：`df365adf937cf8ec3570c1811a2bda388aa936f4b999e870f621eeb7cb55a39d`。
- BIN SHA256：`12ac4afb705d96ded02a18f4bb5798112b71a1117a8e4195a828ebbeb5206c0b`。

| 所属函数 | 跳表地址 | 类型 | 表项数 |
|---|---|---|---:|
| fota_check_parse | 0x08007c8c | TBB | 8 |
| blind_zone_recovery_process.part.0 | 0x0800c2ca | TBH | 21 |
| prepare_operation | 0x0800f3f0 | TBH | 15 |
| prepare_operation | 0x0800f430 | TBB | 9 |
| ch_process | 0x0801176a | TBB | 4 |
| agnss_process | 0x0801307c | TBB | 5 |
| ec800m_process | 0x08013bd8 | TBH | 7 |
| ec800m_process | 0x08013d7c | TBB | 9 |
| query.constprop.0 | 0x080160be | TBH | 21 |
| process_frame | 0x08017708 | TBH | 8 |
| fota_process | 0x08018614 | TBH | 8 |

本次扫描未发现直接跳入这些 CMP 之后、跳表指令之前/本身的已注释分支。但这不是完整控制流证明：尚未排除未知间接入口、表项越界时的额外目标或证明各目标的栈状态。因此 11 处跳表全部仍在 `indirect_transfers` 中；它们的状态 `decoded_local_guard` 仅表示局部模式和目标字节已解码。没有手工目标白名单、ELF 豁免或安全预算放宽。每次 check 均从当前 ELF 重新生成反汇编，既有 ELF/MAP/.su 哈希校验保留。

## 实际验证

在固件仓库执行 `python build/optimization-round6-20260918/verify.py`；自审增加测试、收紧原始十六进制字节识别后，用 `--refresh` 重跑受影响的 5 个栈/RAM 测试、构建、发布门禁和独立检查。每次命令及退出码见 `results.json`，相同最终输入的 host 驱动回归复用已记录结果。

- **已自动验证**：新增测试在修改前工具上因缺少目标证据失败（RED，退出 1）；最终 6 个测试方法通过，包含边界/损坏/旁路子用例。
- 共 14 个测试脚本通过：`stack_table_targets`、`stack_indirect_evidence`、`stack_tail_evidence`、`lto_stack_guard`、`ram_guard`、`heap_bounds`、`ram_watermark`、`stack_health_observability`、`fota_stack_guard`、`feature_guards`、`platform_trust_anchor`、`ec800m_stack_reentry`、`ec800m_urc_demux`、`ec800m_dma_wrap`。
- ARM GNU 14.3.rel1、当前 Makefile，固定 `include/build_version.h`，独立 `BUILD=build/optimization-round6-20260918/final` 构建退出 0。库 parser guard、frame budget test、范围内 `git diff --check` 通过。
- **release-gate 退出 2，未通过**：release-guard 通过后 RAM guard 拒绝 incomplete stack evidence。预期失败码被验证脚本记录不代表门禁通过。它是缺失证明导致的拒绝，不是环境失败。
- make 中断后，单独执行 `platform-trust-guard`、`flash-guard` 均通过。Flash 仍告警 LOW_HEADROOM、CONFIGURATION_CHANGED；后者针对既有容量基线，本轮与第五轮二进制相同另有哈希和字节比较。
- 小范围自审检查新增证据不减少未知项、跨函数目标不丢失后继、半字对齐使用 PC+4、不把 literal 地址当分支、损坏表不输出部分目标集。未进行独立代理审查。
- **需要实机/HIL 验证**：冷启动、验签和 modem 回调叠加、中断/异常嵌套、低功耗唤醒及栈水位。此轮未执行实机验证。

## 是否需要第七轮

**需要，但不应继续把“新增审计字段”当作已经完成 RAM 优化。** 第六轮完成了跳表局部目标取证；第五轮提出的回调写入/来源证明、73 个缺失帧、尾转移、环状态约束及整体运行预算仍未闭合。main 可达缺失帧仍为 55 个；现有 2536 B 不能用作栈上限。

下一轮优先形成能关闭具体缺口的证明：

1. 以本轮精确表地址与目标为输入，补齐可达入口/支配关系及栈状态分析；在此之前不删除跳表未知项。回调需要同样绑定最终 ELF 并覆盖所有写入，不能只复用第五轮的候选清单。
2. 按已保存的最终代码清单，先证明小型库/汇编函数的栈行为，再处理带调用和条件分支的库帧及尾转移。无 `sp` 文本不等于零帧；缺失项不得统一填零。AT 环仍需状态约束证明，路径测试不能替代它。
3. 合并启动残留、堆硬边界、中断嵌套、硬件压栈/FPU/对齐成本，再检查 RAM 门禁。实机水位作为补充证据，不代替最坏路径上限。

Flash 仍仅余 204 B。如转向体积收益，应另选重复分发实现，用真实 C 等价回归与最终二进制测量筛选，不以删功能或恢复机制换空间。本轮没有足够证据推荐某个具体固件重构。

完成第七轮也不能预先承诺发布闭环；停止条件仍是相关回归、完整发布门禁与所需实机/HIL 证据全部满足。
