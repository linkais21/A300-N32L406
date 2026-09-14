# RES-01 Flash 容量门禁实施计划

**Goal:** 准确报告 App BIN 跨度、余量及相对 105776 B 基线的增量，在余量低于 4096 B 时预警，越界或证据不一致时阻断。

**Architecture:** 使用 MAP 中 FLASH 区域及 App/Boot 加载结束符号修正现有计量；独立 Python 门禁核对 App BIN、MAP、ELF 和链接时记录的配置，生成 JSON。Make 的 all/release-gate 和发布脚本共用检查。

**Tech Stack:** Python 标准库、GNU Make、ARM GNU Toolchain。

## 约束与已批准设计

- App 固定 0x08006000..0x08020000，Boot 固定 0x08000000..0x08006000。
- 预警不阻断；超过容量、空/缺失输入、BIN/MAP 不一致必须失败。
- 记录编译器版本、实际参数和配置指纹，配置漂移提示基线不可直接比较。
- 不改变 C 源码、链接布局、版本、RAM gate 预算、日志、OTA 校验或恢复逻辑。
- 不提交、不发布、不烧录；产物放独立 build 子目录。
- BUILD-01 的一般头文件/参数增量依赖问题仍独立存在；发布/验收继续使用 -B 全量构建。

## 执行清单

- [x] 1. 增加临时目录测试：316 B 漏计复现、720 B 预警、4096 B 边界、容量恰满/越界、BIN 截断、MAP 缺符号/错误分区、基线增量、配置漂移、记录与 ELF 不匹配；先运行得到 RED。
- [x] 2. 修改 tools/map_ram_guard.py，新增 tools/flash_capacity_guard.py 与 tools/flash_capacity_baseline.json；最小实现后运行 test_ram_guard.py 和 test_flash_capacity_guard.py 得到 GREEN。
- [x] 3. Makefile 增加 BIN 生成、链接时配置记录、flash-guard；all/release-gate 接入。tools/build_dev_release.py 校验实际发布 BIN 并把容量报告加入发布 manifest 的 artifacts。
- [x] 4. 更新 README 和专项文档；独立目录执行 make -B all、release-gate、OTA/签名/回滚与发布脚本相关 host tests；核验优化前后 BIN SHA256 一致。
- [x] 5. 检查 git diff --check、范围和证据，记录剩余容量风险及未执行的 HIL/部署验证。

测试通过条件示例：105776 B 镜像报告 remaining_bytes=720、delta_bytes=0；102400 B 镜像不触发低余量预警；106496 B 可通过但预警；106497 B 必须失败；105776 B MAP 配 105775 B BIN 必须失败。
