# PERF-04：OTA 校验单次扫描（2026-09-15）

状态：完成第一项优化，PERF-04 尚未整体关闭。依据
`build/quality-audit-20260912/REPORT.md` 的 PERF-04 建议，将正常路径整包
SHA-256 和 body CRC32 合并到同一次 Flash 读取；未将同步校验、ECC 或扇区
擦除改为异步状态机。本轮是源码工程验证，没有生成版本交付包。

## 改动与契约

- `src/fota.c`：每次最多读取 256 B；SHA 包含 32 B header 和整个 body，
  CRC 跳过首块的 header。沿用栈上的 SHA 上下文、读取缓冲与 CRC 累计变量，
  不新增静态工作区。
- 仍按 header/BCR/rollback floor、SHA、签名、CRC、向量检查顺序决定是否接受。
  SHA 失败时仍重新读取 body 计算诊断 SHA/CRC，重新初始化 CRC，保留
  `body_match` 和 `body_crc` 诊断。失败路径不承诺同等性能收益。
- 取消正常路径独立 body 重读；对应读取失败现在统一报告 `stage=package-read`。
  签名、CRC 和独立向量读取的错误分类保留。
- Flash owner、checkpoint、authorization/BCR 提交次序、地址、持久化格式、
  Bootloader 和版本号未修改。
- `tools/tests/test_fota_verify_scan.py`：提取并编译实际校验函数，链接生产
  SHA/CRC，注入 Flash/BCR/签名边界。它不是完整 MCU 模拟；真实签名由既有
  trust-anchor 回归补充验证。

## 可验证收益

设 body 长度为 L，不计调用者读取 header 和 BCR 元数据，保留末尾 8 B 向量读取：

| 正常校验路径 | 候选区读取字节 |
|---|---:|
| 修改前 | 2L + 40 |
| 修改后 | L + 40 |
| 减少 | L |

最大 106,496 B body 的读取量从 213,032 B 降至 106,536 B，减少 106,496 B。
这是主机测试中的 I/O 字节预算，不代表整次 OTA 耗时减半。CRC 计算量未减少；
SHA/签名失败之前现在也执行 body CRC，失败路径可能增加计算耗时。

## 本轮验证

命令在固件仓库根目录运行。普通 `make` 不在 PATH，后改用仓库工具：
`..\tools\w64devkit\w64devkit\bin\make.exe`（下称 make）。

- `python tools/tests/test_fota_verify_scan.py`：修改前在读取预算断言失败（RED），
  修改后通过（GREEN）。覆盖 8 B 最小 body、223/224/225、255/256/257、
  511/512/513 B、最大 body、重复验证、逐次读取失败、owner 拒绝、BCR I/O、
  回滚版本、header、坏 SHA/签名/CRC/向量及失败诊断。主机编译开启
  `-Wall -Wextra -Werror`。
- 对 `tools/tests/test_fota_*.py` 的 12 个脚本和
  `test_ext_flash_store_host.py`、`test_ext_flash_layout.py`、
  `test_internal_flash_layout.py`、`test_platform_trust_anchor.py` 逐个执行
  `python tools/tests/<文件名>`：16 个脚本全部退出 0。
  包含 Range/断线恢复、25,715 个 checkpoint 字节切点场景、4,803 个
  authorization 字节切点场景及真实平台签名/篡改拒绝。
- `make BUILD=build/perf04-20260915 all`：通过，未出现编译器 warning/error。
  App Flash 使用 105,104 / 106,496 B，剩余 1,392 B，有 LOW_HEADROOM 告警。
  配置与历史容量基线不同，不将报告中的历史 delta 当作本次优化收益。
  日志：`build/perf04-build-20260915.log`。
- `make BUILD=build/perf04-20260915 release-gate`：release-guard 通过；
  RAM gate 失败，原因为完整栈/堆/异常上界证据不足。静态 RAM 17,904 B，
  已知调用帧和 2,520 B，扣除两者后剩 4,152 B，但尚未扣除未知堆/IRQ 等开销。
  门禁在此停止；平台签名测试已按上一项独立执行。
  日志：`build/perf04-gate-20260915.log`。
- `git diff --check`：通过。按 requesting-code-review 做范围内自审；不是独立审查。

构建包含工作树原有 `include/debug_uart.h`、`src/debug_uart.c` 修改；本轮未修改它们，
也未修改原有两份诊断文档。正式变更只有上述 C 文件、新测试和本说明。

## 未完成的实机验证及剩余工作

需要实机/HIL 验证：GPIO/DWT 标记整个 VERIFYING、ECC 与单扇区擦除步骤，
结合 SPI 抓取、主循环 worst gap、UART5 DMA 与 GNSS 接收丢包计数，比较前后
最坏时长；进行真实有效/无效升级、Range 恢复及提交切点掉电恢复。

当前 PREPARING 已每次主循环只擦一个扇区，但单扇区内部仍同步等待 WIP；
metadata 写入也同步。扫描及 ECC 仍在一个主循环步骤中运行。后续若分步化，
必须保持跨调用 owner、取消/失败清理、超时、NOR 忙状态与事务恢复，并复核
有限的 Flash/RAM 余量。本轮不声称解除调度阻塞或通过发布验收。

未提交、推送、部署、烧录，也未覆盖现有发布固件。
