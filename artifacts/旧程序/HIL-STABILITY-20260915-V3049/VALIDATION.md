# 本轮验证与改动记录

2026-09-15，当前未提交工作树构建。未覆盖历史固件包，未烧录、提交、推送或部署。

## 命令与结果

工作目录：A300-first。完整实际参数见 validation/commands.json、release-gate-result.json 和各日志。

| 命令/操作 | 本轮结果 |
|---|---|
| `python build/review_stability_3049.py tests` | 64 个定向脚本顺序运行，均退出 0；非 64 个 pytest 用例 |
| `python build/review_stability_3049.py build` | 主 Makefile 新独立目录全量 App/Boot 构建与 HIL 打包成功；无编译器 warning/error |
| 8 个补充脚本 | 串口 F39、F39 端到端、GPS 丢句诊断、NMEA、GPS/NTP、GPS TX 有界、电源里程、生产自检；均退出 0，命令见 supplementary-results.json |
| `make release-gate BUILD=build/stability-review-3049/app`（实际使用 make 绝对路径） | **退出 2，RAM/栈证据不足，正式发布阻断** |
| frame-budget、libc、平台信任锚、Boot 静态容量 | 单独执行通过；不把门禁后未执行依赖假装通过 |
| manifest、OTA header/长度/版本/CRC/向量/公钥、Combined 工厂标记、HEX→BIN 对照 | 通过 |
| 当前源码与 provenance/source-hashes.json 对照 | 通过 |
| `git diff --check`、新增 Markdown UTF-8/行尾检查 | 通过；既有换行符提示保留在日志 |

HIL 打包使用既有工程测试路径，保留 release_approved=false 和失败原始日志；没有修改正式门禁阈值或把 release-gate 改为成功。正式 tools/build_dev_release.py 保持原样。

主回归在版本递增前完成；此后只更新版本字符串/计数/构建时间及其指纹，版本契约与最终包校验在递增后执行。补充脚本针对最终版本执行。

## 本轮实际触碰文件

- `release_identity.json`、`include/config.h`、`include/build_version.h`：V3.049/3049 与本轮构建时间。
- `tools/tests/test_release_identity_contract.py`：同步版本契约期望。
- `tools/release_guard.py`：只刷新版本相关文件指纹，保留校验逻辑与规则。
- `README.md`：新增本次交付入口。
- `docs/quality-closure-v3049-20260915.md`、`docs/HIL-RESULTS-TEMPLATE.md`：完整步骤、17 项映射与记录模板。
- `build/review_stability_3049.py`、`build/stability-review-3049/`：本次独立构建脚本、测试与构建证据。
- 本交付目录及同级 ZIP/校验文件：新产物。

原有 C 业务改动、中科微移除、其他文档和旧发布包均保留。本轮没有重新实现性能功能，不把用户已有优化归为本轮新增改动。

## 未完成验证

需要实机/HIL 验证：全部上电/串口采集、GPIO/时钟/DMA/Flash/Boot 跳转、真实 OTA 与恢复、24h 挂测、路测、低功耗与动态水位/时延。需要测试部署环境验证：实际签名下发、Range 下载、平台最终状态。现场无结果，不能给 17 项签署全部关闭。

本轮性能收益未作同配置 A/B 测量；App 104656 B、静态 RAM 17888 B 是本版资源结果，不是每项优化独立节省值。RAM-01 正式门禁、PERF-01 剩余计算路径及性能测量不足均保留为未闭环。
