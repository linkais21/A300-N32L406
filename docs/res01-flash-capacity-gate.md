# RES-01：App Flash 容量门禁

本项实现容量度量与回归监控，固件节省 **0 B**。105776 / 106496 B、余量
720 B 的容量风险仍然存在，后续代码体积优化应单独验收。

## 规则

- App 固定区间 `0x08006000..0x08020000`，Boot 固定区间
  `0x08000000..0x08006000`，右边界不包含。
- `map_ram_guard.py` 使用 FLASH 区域起点到 `_app_load_end` / `_boot_end`
  的加载跨度。旧算法遗漏 `.data` 加载副本、数组段和对齐，App 少计 316 B。
  区域或结束符号缺失/重复、区域与冻结布局不同均失败，不回退到部分段求和。
- `flash_capacity_guard.py check` 进一步要求 App BIN 长度等于 MAP 加载跨度，
  并核对 ELF SHA-256 与链接时生成的配置记录。缺失/空/损坏输入、越界和
  不一致均退出 1。容量恰满可以通过，但会预警。
- 余量 **严格小于 4096 B** 输出 `Flash guard ALERT LOW_HEADROOM`；退出码仍为 0。
  4096 B 恰好不预警。预警与编译器 `warning:` 分开，发布脚本原有的编译告警
  拒绝规则仍然有效。
- JSON 包含容量、余量、相对基线增量、预警、状态、BIN/ELF/MAP SHA-256、
  配置与配置 SHA-256。输入校验失败也写入 `status=failed`，替换此前的成功报告；
  输出文件不可写时命令失败，消费者必须首先检查进程退出码。

## 基线与配置

`tools/flash_capacity_baseline.json` 固定 2026-09-12 审计、2026-09-13 全量
复现的 105776 B。编译器是 Arm GNU Toolchain 14.3.Rel1 / GCC 14.3.1，
基线记录完整 C/汇编/链接/SDK/签名边界参数和源文件列表。

配置在 ELF 链接成功后写入 `flash-build-profile.json`，绑定 ELF 哈希；
ELF、MAP、HEX、BIN、配置属于 GNU Make 4.3+ grouped outputs，缺少其中一个会
重新链接并重新生成整组，避免旧 BIN/HEX 与新 ELF 混用。
输出 MAP 路径正规化为 `<output.map>`，因此独立输出目录不造成配置漂移。
相对基线配置不同会输出 `CONFIGURATION_CHANGED`，并设置
`baseline_comparable=false`；原始字节增量仍显示，但不能据此归因源码优化收益。
硬件 bringup 配置同样受容量边界约束，但不能与完整功能基线直接比较。

这不是工具链安装锁或通用构建依赖修复。CI 应固定基线工具链和参数，使用
`-B` 全量构建并归档输出；BUILD-01 的普通头文件/参数依赖问题仍独立存在。
配置记录描述本次链接使用的选项，不能证明增量复用的每个对象都由同一选项构建。
不要把秘密放进编译参数；参数属于构建证据。

基线不会自动跟随构建更新。需要更新时，先在固定配置下全量构建、审核容量变化
和所有回归，再以单独可审查修改更新基线。不得仅为消除容量预警调整阈值。

## 命令与产物

在固件仓库根目录运行（make 不在 PATH 时使用本机 GNU Make 绝对路径）：

```powershell
make -B all BUILD=build/res01-validation
make release-gate BUILD=build/res01-validation STACK_AUDIT_BUILD=build/res01-stack
python tools/tests/test_flash_capacity_guard.py
python tools/tests/test_ram_guard.py
```

`all` 生成 HEX/BIN/ELF/MAP、`flash-build-profile.json` 和
`flash-capacity.json`；`flash-guard` 每次调用都检查，不缓存上次结论。
使用已有产物时可单独运行：

```powershell
make flash-guard BUILD=build/res01-validation
```

`tools/build_dev_release.py` 在打 OTA 包前重新检查实际输出的 App BIN，打印
容量和预警，将 `flash-capacity.json` 加入发布 manifest 的
`artifacts.flash_capacity`（包含长度及 SHA-256）。原有版本、向量、签名、
Boot/App 长度和不可覆盖发布目录的检查保持生效。

## 验证范围

新增测试覆盖旧漏计、4 KiB 边界、满容量与越界、空/截断 BIN、缺失符号、错误
分区、旧 ELF 配置、配置漂移、基线非法值、旧成功报告更新及配置记录。
验收以独立目录全量构建和优化前后 BIN 哈希一致为设备代码未改变的证据。
软件门禁不证明运行时栈安全，也不替代 OTA 下载、Range、签名与回滚测试。
未执行生产部署、真实 OTA 或烧录；这些路径仍需要实机/HIL 验证。

## 2026-09-13 实施验收

本轮实际修改/新增文件：

- `Makefile`：同组生成链接产物，增加容量门禁入口。
- `tools/map_ram_guard.py`：App/Boot Flash 加载跨度计量。
- `tools/flash_capacity_guard.py`、`tools/flash_capacity_baseline.json`：容量检查、链接配置记录与冻结基线。
- `tools/build_dev_release.py`：检查发布 BIN，归档容量 JSON 并纳入 manifest。
- `tools/tests/test_flash_capacity_guard.py`、`tools/tests/test_flash_gate_build.py`、
  `tools/tests/test_ram_guard.py`：边界、失败、构建恢复回归；夹具均在临时目录。
- `README.md`、本文、`docs/superpowers/plans/2026-09-13-res01-flash-gate.md`：说明及实施记录。

实际执行以下命令（`make` 使用 `D:/A300_Tools/toolchains/make-4.4.1/bin/make.exe`）：

```powershell
make -B all BUILD=build/res01-20260913-verified
make release-gate BUILD=build/res01-20260913-verified STACK_AUDIT_BUILD=build/res01-20260913-stack
git diff --check
```

全部退出 0，编译日志无编译器 warning/error；新门禁输出：

```text
Flash guard PASS: used=105776/106496 remaining=720 delta=+0 baseline_comparable=True
Flash guard ALERT LOW_HEADROOM
```

以 `python tools/tests/<name>.py` 分别执行以下 15 个脚本，全部退出 0：

```text
test_flash_capacity_guard       test_flash_gate_build
test_ram_guard                  test_dev_release_manifest
test_trust_key_build_dependency  test_hardware_bringup_profile
test_feature_guards             test_ext_flash_layout
test_a300_ota_image              test_fota_package
test_fota_resume                test_fota_platform_flow
test_firmware_signature         test_bootloader_legacy_recovery
test_bootloader_lkg_powercut_c
```

`release-gate` 另执行实际平台签名与篡改拒绝测试。新 Python 文件及修改文件通过
AST 语法检查。Boot MAP 计量以现有审计产物重新运行：12312 / 24576 B、静态 RAM 5 B；
本轮未重新构建 Bootloader。

RED→GREEN 证据包括旧算法 `105460 != 105776`；独立审查发现的缺 MAP/profile
导致旧 BIN/HEX 被复用问题，使用实际 Makefile 和 ARM 工具链复现并修复，
覆盖串行及 `-j4`；关键配置空值/空白拒绝测试同样先失败后通过。
两项审查问题修复后已再次只读复核。

修改前后 BIN 逐字节相同，SHA-256 均为：

```text
0040323198cc72f198ac3bb57d6133e4b0836f1939e7242300bd9a88755a6241
```

本地证据：`build/res01-20260913-build.log`、`build/res01-20260913-release-gate.log`、
`build/res01-20260913-verified/flash-capacity.json`、`host-tests.json`、各测试日志、
`bin-comparison.json`。发布脚本通过相关 host 契约测试及代码审查，未执行会刷新版本头
并创建正式版本目录的完整发布流程；manifest 新增报告的实际发布归档仍需发布环境验证。
未提交、推送、部署或烧录。资源门禁完成不代表 RES-01 容量不足已解决，RAM-01/BUILD-01
也未在本项关闭。
