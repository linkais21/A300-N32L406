# CONC-01：串口命令槽并发所有权（2026-09-15）

状态：代码修复与主机回归完成；需要实机/HIL 验证，尚不作为发布验收。
来源：`build/quality-audit-20260912/REPORT.md` 的 CONC-01。
原审计报告保留为历史证据，本文件记录后续处理。

## 根因与修复

`USART1_IRQHandler` 是 `at_config_feed` 的唯一生产者；主循环调用
`at_config_process`。旧代码在待处理期间仍写命令槽、复制前清除 ready，
且 F39 回退时再次复制共享槽，存在三个覆盖窗口。新主机测试在旧代码上
稳定失败：背靠背两条 TIMER 命令使第一条被替换（RED）。

- `src/at_config.c`：以 GCC 字节原子 acquire/release 传递单槽所有权。
  ISR 写完正文、NUL 并复位写入位置后发布 ready；主循环取得 ready 后
  复制至原有 128 B 局部缓冲，复制完成再释放。此后解析不再读取共享槽。
- `s_cmd_pos` 与新增 `s_cmd_discard` 仅由 ISR 写读；ready 的所有访问均为原子操作。
  无双槽、动态内存、自旋重试或关中断复制；ISR 仍只处理单个字节。
- 槽忙期间后到输入被丢弃。若只收到一部分，槽释放后仍丢弃到 CR/LF，
  防止将后半行识别为独立命令。先提交的命令保留，忙时整行不执行；
  解析期间槽已经释放，可接收下一条完整命令。
- `include/at_config.h`：明确单 ISR 生产者、单主循环消费者、非重入及
  发送端等待命令回复的契约。不承诺无限突发无损，也不新增 busy 回复。
  127 字节上限、超长截断、CR/LF、F39 与 legacy 命令语法沿用原行为。

F39 控制台函数及其解析器读取 const 输入，未识别时直接对同一局部快照
执行 legacy 解析。短信/JT808 入口、持久化、硬件配置和版本号未修改。

## 本轮验证

命令在 A300-first 下运行；`make` 实际为
`../tools/w64devkit/w64devkit/bin/make.exe`。PATH 中没有普通 make，
首次普通 make 调用未执行构建，随后使用上述已有工具。

| 命令 | 结果 |
|---|---|
| `python tools/tests/test_at_config_handoff.py` | RED→GREEN；O0 与 Os+LTO 均通过 |
| `python tools/tests/test_at_config_serial_f39.py` | PASS，真实 F39/legacy 控制台兼容性 |
| `python -m pytest -q -p no:cacheprovider tools/tests/test_at_config_handoff.py tools/tests/test_f39_end_to_end.py tools/tests/test_f39_parser.py tools/tests/test_f39_config.py tools/tests/test_f39_actions.py tools/tests/test_f39_dualset.py tools/tests/test_feature_guards.py tools/tests/test_debug_uart_stats.py` | 4 passed；部分脚本只有 main 入口，另行执行如下 |
| 逐个 `python tools/tests/test_f39_parser.py`、`test_f39_config.py`、`test_f39_actions.py`、`test_f39_dualset.py`、`test_feature_guards.py` | 五个脚本均退出 0 |
| `make -j4 all BUILD=build/conc01-20260915` | PASS，Flash guard PASS；有 LOW_HEADROOM / CONFIGURATION_CHANGED 提示 |
| `make release-gate BUILD=build/conc01-20260915` | FAIL：release-guard PASS，RAM gate 因完整栈/堆/异常证据不足失败，后续依赖未全部执行 |
| `git diff --check` | PASS，仅有工作树换行转换提示 |

新测试链接实际生产模块，用测试包装函数在 strncpy 的每个字节边界
注入 ISR 输入：128 个位置 × legacy/F39 两条路径，共 256 个场景，
每种优化配置均执行。另测待处理覆盖、busy 半行跨释放恢复、解析中
下一条命令入槽及 legacy 回退、重复 process、空行、127 字节边界、
300 字节超长和后续正常命令恢复。它是确定性交错测试，不是 MCU IRQ
时序仿真或真正的多线程压力证明。包装不修改生产源文件。

## 资源与目标指令证据

- App Flash：105,192 / 106,496 B，剩 1,304 B。
- 静态 RAM：17,896 B；已知调用帧和 2,520 B；两者扣除后余 4,160 B，
  尚未扣除未知堆/IRQ 等，不能据此证明 4,096 B 安全间隙。
- 命令槽仍 128 B，新增 discard 对象 1 B；最终 `at_config_process`
  LTO 栈帧 720 B（包含内联解析），main 栈帧 392 B。
  本轮未做同输入的修复前完整构建，不将历史尺寸差值宣传为优化收益。
- 最终 `USART1_IRQHandler` 中可见 `ldrb` 后 DMB 和发布前 DMB + `strb`；
  `at_config_process` 在 strncpy 返回后才 DMB + 清 ready。符号表没有
  外部 atomic 锁实现。交接路径无 cpsid/cpsie，不新增 IRQ 屏蔽时长。
  DMB 和新增分支的真实周期未测，不能承诺 ISR 性能提升。

证据：`build/conc01-build.log`、`build/conc01-gate.log`、
`build/conc01-disassembly.txt`、`build/conc01-20260915/` 中 ELF/MAP/SU
及 stack-analysis.json。隔离构建包含工作树中原有修改，不覆盖发布包。

已按 requesting-code-review 做范围内自审：核对唯一调用上下文、所有
ready 访问、发布/释放顺序、busy 跨行恢复及 F39 const 输入链；非独立审查。

## 实机验收与边界

需要实机/HIL 验证：使用无危险副作用的查询命令，在 115200 baud 下
测试正常请求/回复、背靠背输入、主循环繁忙和 GNSS/UART5 IRQ 压力。
确认已提交命令不被覆盖、不执行被丢弃行的尾部、等待回复后的完整
命令恢复正常；测 ISR 周期及 UART ORE/接收丢失。无真实设备命令发送，
未烧录、部署、提交、推送，也未制作新版本交付包。

本轮正式文件仅为 `src/at_config.c`、`include/at_config.h`、
`tools/tests/test_at_config_handoff.py` 和本说明；保留其他已有修改。
