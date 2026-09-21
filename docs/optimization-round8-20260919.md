# 第八轮复核：栈分析控制流漏报（2026-09-19）

本轮复核第七轮机器码帧证明及其调用图、测试和发布证据。发现两项 P2 分析器缺陷，均已用 ARM GNU 14.3.rel1 汇编器及 objdump 的真实输出复现。未修改固件、分析器、既有测试或门禁；本轮是审查与取证，不是修复完成记录。完整发布门禁仍未通过。

## 复核发现

### R8-01 / P2：条件 BL/BLX 被静默跳过

位置：`tools/stack_usage_guard.py:242`，间接分支的同类限制另见第 256 行。

`analyze()` 仅匹配 `bl`、`bl.w`、`blx`。Thumb IT 块中的真实 objdump 输出为 `bleq`、`blxeq` 等，因此条件直接调用不建立边，条件寄存器调用也不记录未知项。条件是否成立未知时，应保留执行该调用的路径。

本轮三个真实汇编夹具中的前两个证明：

- `conditional-direct.s`：main 帧 8 B，条件调用 worker；worker 实际执行 `sub sp, #128` / `add sp, #128`。传入与指令一致的帧表后，返回 main 已知帧和 8 B（漏掉可达的 128 B），`call_edges.main=[]`，`complete=true`。
- `conditional-indirect.s`：main 在 IT 块执行 `blxeq r3`，报告却为 `indirect_transfers=[]`、`complete=true`，未知目标消失。

这不只是未来编译形式的假设：当前本轮最终 ELF 的 main 已知图可达浮点库中，存在被跳过的 `0x080192a4: bleq 0x08019464 <__aeabi_dmul+0x1dc>` 与 `0x080194f8: bleq 0x0801964a <__aeabi_ddiv+0x16e>`。这两处是函数内部子程序入口，不能简单视为正常函数入口帧；需要保留内部调用的栈状态证明义务。本轮未据此推算新的 main 最坏栈上限。

建议按指令类别与条件执行语义处理 BL/BLX/BX，条件寄存器转移至少保留为未解决；直接内部入口必须显式保留缺口。不能简单剥离任意助记符后缀，以免混淆 B.LE 与 BL 等不同指令。补充真实反汇编回归，确认已知帧和与可达缺口能沿这些边传播。

### R8-02 / P2：跨函数 CBZ/CBNZ 没有进入尾转移图

位置：`tools/stack_usage_guard.py:248`。

直接分支正则只覆盖 B/Bcc，未处理 `cbz` / `cbnz`。当比较分支跳往相邻函数或函数内部入口时，目标的帧和后继未知项不会传播到调用根，尾转移本身也消失。`table_target_evidence()` 虽识别这两类指令用于旁路检查，但不会补齐普通调用图。

`compare-branches.s` 中 main 零帧，通过 `cbz r0, worker` / `cbnz r1, worker` 跳到 128 B 帧的 worker。真实编译反汇编输入得到 `call_edges.main=[]`、`tail_transfers=[]`、main 已知帧和 0 B、`complete=true`。实际可达路径至少需要 worker 的 128 B。

本轮当前固件反汇编未发现跨函数 CBZ/CBNZ；该项为工具已复现的覆盖缺陷，不能表述成当前固件已发生栈溢出。建议复用直接尾转移处理，保留目标内部偏移的不确定性，并测试局部分支不误报、跨函数后继传播及缺帧拒绝。

两项缺陷影响 `analyze()` 的局部完整性和路径诊断。当前 `check()` 仍输出 incomplete，`map_ram_guard.py` 仍拒绝 App 未证明的运行预算，因此本轮没有发现由这两项导致的发布放行。报告中的间接/尾转移计数仅为当前工具已识别数量，不能视为完整清单。

## 第七轮结论复核

- 第七轮记录的 333 个输入中已有 9 个改变：`src/at_config.c`、`src/flash_config.c`、`include/build_version.h`、`include/config.h`、`tools/release_guard.py`，以及 `test_at_config_serial_f39.py`、`test_flash_config_v3.py`、`test_fota_modem_handoff.py`、`test_release_identity_contract.py`。这些均为进入本轮前的变化。
- 第七轮记录的分析器及两个改动测试的 SHA256 未变。本轮不复用旧版本容量，使用当前 V3.063、固定现有版本头，在独立目录重新构建。
- 第七轮补齐的五个缺帧仍成立：`__errno` 和两个递归锁函数为 0 B；`_init`、`_fini` 为 24 B。当前所有 6 个机器码证明（另含已有编译器帧的 `uECC_secp256r1`）的字节均与本轮最终 BIN 核对一致；不会下调已有编译器帧。
- 11 处跳表、115 个表项、195 字节与当前 BIN 一致；这些局部证据仍未获得完整控制流信用。
- 未发现第七轮限定直线指令子集的新增错误授信。该结论不等于对整个 Thumb 指令集或异常运行预算的证明。

## 当前输入的验证结果

执行：`python build/optimization-round8-20260919/verify.py`。每条子命令、退出码和日志保存于同目录 `results.json`。验证脚本对缺陷夹具断言当前错误行为用于复现，不是修复后的验收测试；其最终退出 0 不表示发布通过。

| 项目 | 第七轮记录 | 本轮重新验证 |
|---|---:|---:|
| App BIN / Flash | 106292 B | 106376 B |
| App 分区余量 | 204 B | 120 B |
| 静态 RAM | 17716 B | 17716 B |
| main 已知帧和（非上限） | 2536 B | 2536 B |
| 已识别全局缺失帧 / main 可达缺失帧 | 68 / 52 | 68 / 52 |
| 已识别间接转移 / 尾转移 / 环 | 67 / 131 / 1 | 67 / 130 / 1 |

- **已自动验证**：`stack_machine_frames`、`stack_table_targets`、`stack_indirect_evidence`、`stack_tail_evidence`、`lto_stack_guard`、`ram_guard` 六个现有测试脚本退出 0；三个真实汇编夹具复现上述漏报。
- **构建**：ARM GNU 14.3.rel1，当前 Makefile，`BUILD=build/optimization-round8-20260919/final`，`-o include/build_version.h`，`make -j4 all` 退出 0。
- **发布门禁失败**：`release-gate` 退出 2。第一项失败是 RAM guard 的 `incomplete stack evidence`，不是环境失败；release-guard 先行通过。静态 RAM 扣除已知帧和后剩 4324 B，仍须容纳尚未证明的堆、中断及其他成本，不能据此宣布安全。
- **独立门禁**：被 RAM 失败跳过的 `platform-trust-guard`、`flash-guard` 单独运行通过。Flash 告警 `LOW_HEADROOM`、`CONFIGURATION_CHANGED` 保留。
- 输入哈希前后核对一致，文件清单见 `input-hashes.json`、`final-input-hashes.json`。ELF SHA256：`e4a165fa96bc87843d506d4e3626f8968f96dcf454e3e8e254c8d1fe45e0b42a`；BIN SHA256：`9210d35283d22e1b41784fef0e132121e896345d684001bd014cedf6d3fd4069`。
- **需要实机/HIL 验证**：冷启动、验签与 modem 回调叠加、中断/异常嵌套、低功耗唤醒及栈水位。本轮未执行这些项目，也未重跑与本次分析器复核无关的全部功能测试。

## 本轮文件与后续

仅新增本文及 `build/optimization-round8-20260919/` 下验证脚本、汇编夹具、复现报告、输入哈希、构建和日志。未修改业务源码或分析器，未提交、推送、烧录或覆盖交付包。

优先修复 R8-01/R8-02 并做 RED→GREEN，再扩展带局部循环的库函数机器码证明。其后仍需处理缺失帧、回调写入来源、内部入口、调用环、启动残留和完整堆/IRQ 预算。本轮没有关闭新的栈缺口或产生体积优化收益，不能作为发布收尾结论。
