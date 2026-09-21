# 第七轮保持功能优化：关闭五个机器码栈帧缺口（2026-09-19）

本轮完成有限 Thumb 直线函数的机器码栈帧证明，实际关闭 5 个缺失帧。发布门禁仍未通过，建议继续第八轮。此轮没有 Flash/RAM 体积收益，不代表整体 RAM 安全已证明。

## 实际改动与证据

- `tools/stack_usage_guard.py`：新增 `machine_frame_evidence`。按原始 Thumb 编码识别限定的 PUSH、POP（不含 PC）、MOV、低寄存器加载和 NOP，跟踪栈深度与入口 LR 来源；仅在连续地址、栈平衡且 BX LR 返回原入口 LR 时接受。未知编码、调用、分支、IT、SP/PC 改写、栈下溢、缺指令与异常处理入口均不授予证明。报告记录代码地址、原始字节和帧峰值。成功证明只补缺少 .su 的函数，不覆盖编译器帧，不清除间接、尾转移或环缺口。
- `tools/tests/test_stack_machine_frames.py`：8 个测试方法，覆盖零帧、非零峰值、嵌套压栈、返回地址被覆盖、缺字节、宽指令、未知指令、非对齐入口、异常入口、编译器证据优先和调用路径帧和。
- `tools/tests/test_stack_tail_evidence.py`：原来的未知库函数夹具为 BX LR，现在可证明为零帧；改成未支持的局部循环，保留“未知后继必须传播”的断言。
- `docs/superpowers/plans/2026-09-19-preserve-features-round7.md`、本文：本轮范围、结果与第八轮评估。
- `build/optimization-round7-20260919/`：修改前工具快照、输入/最终哈希、RED 重放及退出码、验证脚本和各命令日志、独立构建、跳表字节核对、剩余缺帧清单、与本轮起始状态比较的分析器补丁。

进入本轮时，第六轮保存的输入哈希均未变化。本轮仅上述工具、测试及文档发生修改；所有既有固件修改保留。没有提交、推送、部署、烧录或覆盖交付包。使用执行计划、测试先行、计划编写及验证技能，并完成范围内自审；未使用独立代理审查。

## 证明结果

| 函数 | 帧峰值 | main 已知图可达 |
|---|---:|---|
| `__errno` | 0 B | 是 |
| `__retarget_lock_acquire_recursive` | 0 B | 是 |
| `__retarget_lock_release_recursive` | 0 B | 是 |
| `_init` | 24 B | 否（启动路径另计） |
| `_fini` | 24 B | 否 |

证明以正常 ABI 函数入口 SP/LR 为前提；加载可能触发的异常、硬件压栈及嵌套成本仍由未完成的运行预算负责。直线前缀在 BX LR 结束，随后 literal/padding 不执行。内部地址入口不因此获得信用，相关尾转移仍未解决。不使用函数名白名单或把“看不到 sp”当成零帧。

| 指标 | 第六轮 | 第七轮 |
|---|---:|---:|
| App BIN / Flash | 106292 B | 106292 B |
| App 分区余量 | 204 B | 204 B |
| 静态 RAM | 17716 B | 17716 B |
| main 已知帧和（非上限） | 2536 B | 2536 B |
| 全局缺失帧 | 73 | 68 |
| main 可达缺失帧 | 55 | 52 |
| 未解决间接转移 | 67 | 67 |
| 未证明尾转移 / 调用环 | 131 / 1 | 131 / 1 |

最终 ELF/BIN 与第六轮相同。ELF SHA256：`df365adf937cf8ec3570c1811a2bda388aa936f4b999e870f621eeb7cb55a39d`；BIN SHA256：`12ac4afb705d96ded02a18f4bb5798112b71a1117a8e4195a828ebbeb5206c0b`。本轮所有机器码帧证据及 11 处跳表的 115 个表项、195 字节均与最终 BIN 核对一致。

## 实际验证

执行 `python build/optimization-round7-20260919/verify.py`，自审增加边界测试与奇地址拒绝后执行 `--refresh` 重跑受影响的 6 个栈/RAM 脚本、构建与门禁。其余未变化输入的回归复用首轮记录。每条命令与真实退出码见 `results.json`；最终代码哈希见 `changed-code-hashes.json`。

- **已自动验证**：最终 8 个新增测试在本轮起始工具快照上退出 1（缺少帧证明），当前实现退出 0；RED 日志和 `red_replay.py` 可复现。
- 共 15 个测试脚本通过：`stack_machine_frames`、`stack_table_targets`、`stack_indirect_evidence`、`stack_tail_evidence`、`lto_stack_guard`、`ram_guard`、`heap_bounds`、`ram_watermark`、`stack_health_observability`、`fota_stack_guard`、`feature_guards`、`platform_trust_anchor`、`ec800m_stack_reentry`、`ec800m_urc_demux`、`ec800m_dma_wrap`。
- ARM GNU 14.3.rel1、当前 Makefile、固定版本头，独立 `BUILD=build/optimization-round7-20260919/final` 构建退出 0。libc parser guard、frame budget test、范围内差异检查通过。
- **release-gate 退出 2，未通过**：release-guard 通过后，RAM guard 因 incomplete stack evidence 拒绝。不是环境失败；验证脚本接受预期退出码仅用于继续收集证据，不代表门禁成功。
- 被上述失败跳过的独立 `platform-trust-guard`、`flash-guard` 单独执行通过。Flash 仍告警 LOW_HEADROOM、CONFIGURATION_CHANGED；后者相对于既有容量基线，本轮与第六轮另有相同二进制证据。
- **自审**：原始编码决定栈效果；返回令牌被常量/加载覆盖则拒绝；栈欠账、奇地址、未知宽指令和条件执行不接受；已有 .su 帧不下调。没有更改门禁预算或添加豁免。
- **需要实机/HIL 验证**：冷启动、验签与 modem 回调叠加、中断/异常嵌套、低功耗唤醒和栈水位。本轮未进行硬件验证。

## 是否需要第八轮

**建议继续，目标应是进一步关闭实际缺口。** 目前仍有 68 个缺失帧（main 可达 52 个）、67 个间接转移、131 个尾转移及 1 个调用环；2536 B 不能当作栈上限。第七轮只完成小型直线函数，不能把这部分进展视为第六轮提出的全部证明义务已完成。

1. 优先为 `strlen`、`strcmp`、`memcpy`、`memcmp` 等库函数建立最终机器码的局部控制流/栈状态分析：分支目标必须落到指令边界，所有可达路径和循环回边保持可验证栈状态，返回地址来源可追溯；未知指令、内部入口、非零栈增量循环继续拒绝。不要仅扩充助记符白名单。
2. 再处理调用型库帧、浮点库跨函数内部尾入口、回调全部写入来源及 AT 防重入状态约束。现有跳表局部证据仍缺支配关系和目标栈状态证明。
3. 只有上述路径证据足够后，才合并启动残留、堆硬边界、中断嵌套和硬件/FPU/对齐成本，重新评估完整 RAM 门禁。HIL 水位提供补充，不能代替最坏路径分析。

若下一轮目标改为直接节省 Flash，应单独选择有等价回归的具体重复实现进行测量；本轮不提供新的固件重构候选。第八轮是否能够收尾仍取决于证据，不预先承诺发布通过。
