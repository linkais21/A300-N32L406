# 第三轮保持功能优化（2026-09-18）

承接第二轮当前未提交工作树，本轮只改变 ICCID 编码内部实现，保留所有功能、日志、协议、非法输入拒绝、身份校验及容量检查。未改版本、构建参数、Flash 布局、Bootloader 或交付包。

## 变更与实测

- `src/jt808_terminal_info.c`：移除 20 字节中间半字节数组，直接生成 10 字节 ICCID；19 位输入仍在报文最前面补零半字节，20 位输入保持原序，大写/小写十六进制保持支持。
- `tools/tests/test_iccid_encoding_equivalence.py`：实际 C 编码入口的等价测试。覆盖两种长度中每个位置的全部合法字符、每个位置的其余非零字节拒绝、0～21 的非法长度、容量不足、空指针和输出尾部哨兵。支持 `--source` 检查起始源码快照。多位混合值另由已有 `test_terminal_identity.py` 覆盖。
- 本文记录结果及后续建议。

使用 ARM GNU 14.3.rel1、当前 Makefile、固定版本头、独立构建目录：

| 指标 | 基线 | 最终 | 变化 |
|---|---:|---:|---:|
| App Flash / BIN | 106324 B | 106292 B | -32 B |
| 104 KiB App 分区余量 | 172 B | 204 B | +32 B |
| 静态 RAM（map guard） | 17716 B | 17716 B | 0 |
| 终端信息编码局部栈帧（LTO .su） | 88 B | 80 B | -8 B |
| 已知 main 最深调用链帧和 | 2536 B | 2536 B | 0 |

局部栈减少不代表全程序栈上限减少。没有 MCU 耗时测量，不宣称 CPU 性能提升。Flash 仍为 LOW_HEADROOM。

## 验证

在固件仓库下使用 `../tools/w64devkit/w64devkit/bin/make.exe`：

```text
make BUILD=build/optimization-round3-20260918/baseline -o include/build_version.h all
make BUILD=build/optimization-round3-20260918/final -o include/build_version.h all
make BUILD=build/optimization-round3-20260918/final -o include/build_version.h release-gate
make BUILD=build/optimization-round3-20260918/baseline -o include/build_version.h -o src/jt808_terminal_info.c ram-guard
```

基线、最终构建与 Flash guard 通过。基线门禁显式保持旧源码目标不重建，日志确认没有将基线重新编译为候选。

以下 9 项 `python tools/tests/test_<name>.py` 均退出 0：

```text
iccid_encoding_equivalence terminal_identity jt808_boot_terminal_info
jt808_dual_session jt808_registration_tx jt808_session_send_failure
jt808_send_failure_contract feature_guards platform_trust_anchor
```

新增测试在修改前源码和最终源码上均通过，属于等价重构验证，不是缺陷 RED→GREEN。测试搭建最初缺少 host `n32l40x.h`，补充空硬件头夹具后通过；未修改生产头或测试断言。

release-guard、libc parser guard 和任务源码 `git diff --check` 通过。**完整 release-gate 未通过**：ram-guard 仍缺少完整栈证据。基线和最终均为 73 个缺失帧、56 个间接转移、131 个尾转移、1 个环，未降低门禁要求。

证据在 `build/optimization-round3-20260918/`：起始源码 `before.c`、输入及最终哈希、基线/最终 ELF/map/.su、构建日志、逐项命令/退出码 `results.json` 和任务 `task.diff`。输入哈希确认仅 `src/jt808_terminal_info.c` 发生生产输入变化；其余已有工作树改动保留。辅助验证脚本为该目录内 `verify.py`。

需要实机/HIL 验证：使用 19/20 位 ICCID 的 0x0107 上报、运行栈水位，以及发布要求的设备回归。未提交、推送、部署、烧录或覆盖交付固件；本轮产物仅用于比较。

## 第四轮建议

仍可继续，但前几轮微优化收益只有几十字节，当前 204 B 余量并不足以消除容量风险。建议第四轮优先补齐库函数栈帧、间接调用目标、尾调用和中断/异常栈证据，建立可审计的全程序 RAM 上限；若要继续压缩 Flash，应重新按链接符号大小筛选重复实现，并用完整构建确认收益。两者都是待开展工作，尚未承诺可节省的字节数或门禁必然通过。
