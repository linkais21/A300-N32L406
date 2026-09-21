# 第五轮保持功能优化：间接转移与 AT 防重入证据（2026-09-18）

本轮完成跳表漏报修正、AT 防重入路径测试和最终链接回调候选审计。全程序 RAM 上限仍未证明，release-gate 仍失败，需要第六轮。此轮收益是补全证据，Flash/RAM 没有减少；固件 BIN 与第四轮逐字节相同。

## 本轮实际改动

- `tools/stack_usage_guard.py`：将 TBB/TBH 纳入未解决间接转移，并保留到各入口的可达缺口；间接转移新增 `kind` 分类（寄存器调用、寄存器跳转、PC 写入、跳表）。已有字段、未知返回指令和门禁拒绝逻辑保留。
- `tools/tests/test_stack_indirect_evidence.py`：4 个测试，覆盖 TBB/TBH、非 PC 基址、IRQ 独立可达、未证明返回和回调保留，以及相似非分支指令/表数据不误报。
- `tools/tests/test_ec800m_stack_reentry.py`：复用现有硬件桩、编译真实完整 `ec800m.c`，增加 6 组路径测试和 3 组临时源码突变拒绝验证。
- `docs/superpowers/plans/2026-09-18-preserve-features-round5.md`、本文：范围、验收、结果和剩余工作。
- `build/optimization-round5-20260918/`：独立构建和验证证据，包括 `verify.py`、`audit_callbacks.py`、起始分析器快照、输入/最终哈希、命令退出码、日志、回调审计与最终链接输出。没有改写已有交付包。

## 定量结果

ARM GNU 14.3.rel1、当前 Makefile、固定版本头，使用同一源码和配置。

| 项目 | 第四轮 | 第五轮 |
|---|---:|---:|
| App Flash / BIN | 106292 B | 106292 B |
| App 分区余量 | 204 B | 204 B |
| 静态 RAM（map guard） | 17716 B | 17716 B |
| main 已知帧和 | 2536 B | 2536 B |
| 全局缺失帧 | 73 | 73 |
| 全局未解决间接转移 | 56 | 67 |
| main 静态可达未解决间接转移 | 48 | 58 |
| 全局未证明尾转移 / 调用环 | 131 / 1 | 131 / 1 |

新增 11 处是以前漏报的跳表，非运行行为恶化。67 处由 34 个寄存器调用、4 个寄存器跳转、18 个 PC 写入、11 个跳表组成。main 静态可达 394 个函数、55 个缺失帧和 94 个未证明尾转移，仍可达调用环。未解析的间接目标可能引入更多函数，这不是完整运行调用图。分析器仍不是通用 ARM 控制流/栈证明器。

最终 ELF SHA256：`df365adf937cf8ec3570c1811a2bda388aa936f4b999e870f621eeb7cb55a39d`。

最终 BIN SHA256：`12ac4afb705d96ded02a18f4bb5798112b71a1117a8e4195a828ebbeb5206c0b`。

## 回调候选与证据边界

审计结果绑定上述最终 ELF/BIN、反汇编和符号清单的哈希，见 `callback-audit.json`、`indirect-sites.json`。未把以下候选当作完整目标集合，也未加入手工豁免。

| 边界 | 本轮核对 | 尚缺证明 |
|---|---|---|
| micro-ecc | `curve_secp256r1` 位于只读地址 `0x0801fd40`，176 B；BIN 中 +164/+168/+172 三个 Thumb 指针分别对应 `double_jacobian_default`、`x_side_default`、`vli_mmod_fast_secp256r1`。`uECC_verify` 的 `0x0801be8c` 调用从 curve+164 取指针；`uECC_vli_modMult_fast` 的 `0x0801b97e` 从 curve+172 取指针。验签包装器显式获取 secp256r1。 | 每个可达调用点的 curve 来源和传播证明；回调后继帧也必须纳入。常量槽核对不等于全程序指针分析。 |
| F39 | `f39_bind_defaults` 最终 literal pool 中 16 个函数地址与默认持久化、定时器、重连、认证重置、PDP、GNSS、注册、AGNSS、继电器、FOTA、GPS/继电器查询、短信发送/结果、延迟复位目标一致。源码存在 `at_config_bind_f39` 覆盖入口，但最终符号表没有该符号。 | RAM 平台表所有写入、初始化时序和每个 callsite 的字段来源；不能仅凭覆盖函数符号消失排除内联或其他写入。 |
| modem | 源码注册候选为 `jt808_on_recv`、`fota_ec800m_rx`、`agnss_network_rx`；最终 `ec800m_process` 有 `0x08013ae6` 和 `0x08013c38` 两个寄存器调用，已保存邻近取指令。 | 通道条件、所有写入、初始化/重初始化及非空判断的最终链接绑定；不能从源码注册函数个数推断机器码间接调用个数。 |

## AT 调用环的路径测试

真实驱动的 6 组测试通过：

1. SMS 持有 AT owner 时，阻塞命令被拒绝、队列不执行；释放后可处理。
2. `+QIOPEN` 错误出队引发 `QICLOSE`，等待期间注入第二通道错误；第二条只排队，当前出队结束后才处理，重复空调用无额外命令。
3. `QICLOSE` 无响应时有界超时、owner/防重入状态释放，下一条命令能成功。
4. 入队后通道 generation 改变时，不执行过期工作。
5. 防重入标志、QIRD 活跃、UDP 活跃时不出队，解除后恢复。
6. 队列容量上限、逐次单条处理及 recv 仅置 pending、不立即启动 QIRD。

临时源码去掉防重入条件、忽略阻塞 owner 获取失败、去掉 generation 判断，各自被对应断言拒绝。变体只存在于自动清理的临时目录，生产源码未改。这证明这些具体路径上的保护有效；硬件桩不覆盖完整 SMS/回调行为、所有交错或最终 ARM 栈。因此保留第四轮报告的调用环，不推断实机无限递归，也不将它从栈证据删除。

## 实际验证

构建入口（固件仓库根目录，使用工作区 `../tools/w64devkit/w64devkit/bin/make.exe`）：

```text
make BUILD=build/optimization-round5-20260918/final -o include/build_version.h all
make BUILD=build/optimization-round5-20260918/final -o include/build_version.h release-gate
```

- **已自动验证**：新增跳表测试对修改前分析器为 4 次断言失败、1 次缺少分类字段错误（含子用例），最终 4 个测试全部通过。旧工具在只有跳表的夹具中错误返回 `complete=true`，修正后为 false。
- 13 个测试脚本均退出 0：`stack_indirect_evidence`、`stack_tail_evidence`、`lto_stack_guard`、`ram_guard`、`heap_bounds`、`ram_watermark`、`stack_health_observability`、`fota_stack_guard`、`feature_guards`、`platform_trust_anchor`、`ec800m_stack_reentry`、`ec800m_urc_demux`、`ec800m_dma_wrap`。
- 首次构建退出 2：验证脚本临时 PATH 引入 w64devkit 的 sh，误解析 Makefile 的 Windows `if not exist`；去掉该 PATH 修改后构建退出 0。失败保留在 `build.log` 和 `results.json`，最终成功在 `build-final.log`。
- Flash guard 通过，仍提示 LOW_HEADROOM 和相对既有基线的 CONFIGURATION_CHANGED；本轮与第四轮 BIN 逐字节相同的结论独立于该基线。
- **release-gate 退出 2**：release-guard 通过，随后 RAM guard 因栈证据 incomplete 拒绝。没有绕过拒绝、修改 RAM 预算或删除安全控制；后续依赖门禁没有因 make 中断而被视为通过。
- `test_ram01_frame_budget.py <final-build>`、libc parser guard、回调只读槽/地址核对及范围内差异检查通过。采用 requesting-code-review 的小改动自审流程，检查分类兼容、未知项保留、入口可达和测试突变隔离。
- 输入哈希比较确认既有输入仅改变 `tools/stack_usage_guard.py`；新增测试和文档另列。未创建提交、推送、部署、烧录或改动交付固件。
- **需要实机/HIL 验证**：冷启动、OTA 验签与 modem 回调叠加时的栈水位，中断/异常嵌套及低功耗唤醒。此轮未执行这些验证。

## 是否还有第六轮

**有。理由是发布验收条件未闭合，不是预设优化轮数。**

第六轮优先处理以下有证据依据的剩余项：

1. 将已定位的只读曲线槽、F39/modem 回调和 11 处跳表转换为逐调用点可验证的目标集合；必须拒绝 ELF 变化、槽变化、未覆盖写入和未知表边界。AT 测试作为路径证据，不能代替状态约束与最终机器码证明。
2. 补齐 73 个缺失函数帧和尾转移/返回的栈行为；把剩余环约束、启动残留、中断/异常嵌套、硬件/FPU/对齐开销与 1024 B 堆硬边界合并为整体 RAM 预算。2536 B 仅为已知帧和，不是栈上限。
3. 若继续要求 Flash 体积收益，独立筛选重复命令/配置分发实现，先建立真实 C 等价回归，再测量最终构建；204 B 余量仍不足以支持未经测量的功能扩展。不可删功能、诊断或恢复逻辑换空间。

停止条件：相关 host 回归、Flash 与完整发布门禁通过，硬件风险取得实机/HIL 证据。第六轮是否能达到这些条件仍取决于实际证据，不能预先承诺一定收尾。
