# P3：`-finline-limit=32` 当前源码对照评估

日期：2026-09-18。结论：**不采用 32，保留默认 64**。本轮 32 比 64 多占 240 B Flash，静态 RAM 无收益。历史“节省 200 B”不适用于当前源码，不能作为余量危机时的备用方案。

## 输入与方法

- HEAD：`6eab8e68391ead12b0d280aea441e641c2614389`，包含评估时工作树的已有修改；不是仅构建 HEAD。
- 工具链：Arm GNU Toolchain 14.3.Rel1，GCC 14.3.1 20250623。
- 使用当前 Makefile，保留 `-Os`、LTO、硬浮点和 main/FOTA/签名/uECC 的既有单次调用内联限制。唯一参数变量是编译和 LTO 链接共同使用的 `-finline-limit=64/32`。
- 两组使用全新的独立输出目录；未调用会刷新版本时间戳的 `all`，而是执行 `size flash-guard`，两者会触发完整编译、链接及 ELF/MAP/HEX/BIN 生成。未改默认 Makefile、源文件、版本或原有固件产物。
- `build-inline-eval-20260918/source-hashes.json` 保存源码、头文件、SDK、第三方代码、链接脚本、Makefile 的 SHA-256；构建后全部比对一致。
- 审计原文的 106176 B / 静态 RAM 18068 B 是较早工作树结果；本轮重新构建的 106160 B / 17756 B 才是本次对照基线，不能跨输入计算优化收益。

可重跑命令（在仓库根目录；更换 BUILD 目录可重新保留一组证据）：

```powershell
mingw32-make -j4 BUILD=build-inline-eval-20260918/64 "SIZE_FLAGS=-Os -finline-limit=64 -fno-inline-functions-called-once" size flash-guard
mingw32-make -j4 BUILD=build-inline-eval-20260918/32 "SIZE_FLAGS=-Os -finline-limit=32 -fno-inline-functions-called-once" size flash-guard
mingw32-make BUILD=build-inline-eval-20260918/64 "SIZE_FLAGS=-Os -finline-limit=64 -fno-inline-functions-called-once" ram-guard
mingw32-make BUILD=build-inline-eval-20260918/32 "SIZE_FLAGS=-Os -finline-limit=32 -fno-inline-functions-called-once" ram-guard
```

## 实测

| 指标 | 默认 64 | 候选 32 | 32 − 64 |
|---|---:|---:|---:|
| App Flash 加载跨度 / BIN | 106160 B | 106400 B | **+240 B** |
| App 分区剩余 | 336 B | 96 B | −240 B |
| size 的 text | 105840 B | 106080 B | +240 B |
| size 的 data | 312 B | 312 B | 0 |
| 静态 SRAM（map guard，不含堆栈预留） | 17756 B | 17756 B | 0 |
| 已知 main 调用链帧和 | 2408 B | 2408 B | 0 |
| 扣除静态 RAM 和已知帧和的空间 | 4412 B | 4412 B | 0 |
| 缺失栈帧 / 间接跳转数 | 76 / 52 | 76 / 53 | 0 / +1 |

两组构建和 flash-guard 均退出 0，均提示 LOW_HEADROOM、CONFIGURATION_CHANGED。guard 内置历史 baseline 不可比，本报告只计算同次两组的差值。两组 `ram-guard` 均退出 2：首个真实失败是栈证据不完整，不能认定整体 RAM/栈安全通过；上述 4412 B 尚未扣除堆、IRQ 和未知帧。

## 代码生成与风险

降低内联阈值并不保证缩小最终镜像；全程序 LTO 会重新选择内联、函数拆分及跨函数优化。最终符号中，`main` 从 2344 增至 2504 B，`USART1_IRQHandler` 从 32 增至 128 B；`work_mode_process` 从 1308 降至 1168 B，`scan_alarms` 从 388 降至 288 B。部分符号出现或消失（含 `.part.0` 拆分），不能将单个符号的变化直接解释为完整业务功能大小或执行耗时。

32 未减少已知最深调用链帧和，并改变中断路径的代码生成；没有实测性能收益，也不能由镜像大小或指令数量推导具体延迟。若未来源码或工具链变化后重新考虑该参数，必须重新做同输入 A/B，并对中断接收、主循环耗时、OTA 验签及栈水位进行实机/HIL 验证。

证据目录：`build-inline-eval-20260918/`，包含两组构建与 RAM 日志、`commands.json`（每条命令的退出码）、源码哈希、符号列表、`symbol-diff.json`，以及各自的 ELF/MAP/BIN、构建参数、容量和栈分析报告。

本轮仅做编译参数评估及文档更新；未运行无关 host 测试或完整发布门禁，未烧录、部署或提交。硬件行为与性能**需要实机/HIL 验证**；本候选不进入发布配置。
