# PERF-05：移除闲置中科微定位模块支持

2026-09-15：用户确认当前不使用中科微模块，按移除处理流解析反复搬移的二次复杂度候选，不再优化该解析器。

## 行为与兼容

- 删除中科微 CASBIN/CSIP 解析器、公开接口、构建输入和工作区 owner；网络及离线注入仅支持 TAU804M。
- AGNSS 调度遇到非 TAU804M 配置立即返回，不再读取并重试中科微星历。
- 历史 `GNSS_TYPE_ATGM332D_F7N=2` 保留为退役的持久化编号，不重编号、不自动重写旧配置。该配置的 GPSBDS 设置返回 `unsupported-receiver`，不保存配置、不发送模式命令。
- TAU804M 流缓冲仍为 4096 字节；Flash 配置/星历布局、凭据字段和历史产物保持兼容。通用 GPS 串口和当前使用的 PCAS 命令不属于本次删除的专用星历解析器。

## 本轮文件

- 删除：`src/agnss_zhongkewei.c`、`tools/tests/test_zhongkewei_agnss.py`。
- 修改：`Makefile`；`include/agnss_storage.h`、`include/agnss_vendor.h`、`include/agnss_stream_workspace.h`；`src/agnss_huada.c`、`src/agnss_manager.c`、`src/f39_reply.c`。
- 更新测试：`tools/tests/test_agnss_vendor_stream.py`、`test_agnss_scheduler.py`、`test_agnss_workspace_ownership.py`、`test_f39_actions.py`、`test_hardware_bringup_profile.py`。
- 新增本文；验证产物写入独立目录 `build-perf05-retire-zk/`。保留工作区此前已有修改。

## 自动验证

新增拒绝旧型号注入、停用旧型号调度、拒绝旧型号 GPSBDS 三项真实 C 回归先在原实现上失败，移除后通过。

以下命令通过（各测试使用 `python tools/tests/test_<name>.py`）：

- `agnss_vendor_stream`、`agnss_workspace_ownership`、`agnss_scheduler`、`agnss_snapshot`、`agnss_storage`。
- `f39_actions`、`flash_config_migration`、`hardware_bringup_profile`、`feature_guards`。
- 构建配置测试最初被已有代码的空格变化触发；断言改为忽略空白后通过，仍检查相同的 bring-up 桩函数。
- `make all BUILD=build-perf05-retire-zk`：通过。PATH 无 make，实际调用已安装 STM32CubeIDE 的 `make.exe` 绝对路径。
- Flash guard：104656 / 106496 字节，余 1840 字节；提示 LOW_HEADROOM、CONFIGURATION_CHANGED，历史基线不可直接比较。
- `python tools/release_guard.py`：通过。
- `git diff --check`：通过。

`make ram-guard BUILD=build-perf05-retire-zk` **失败**：全程序栈/堆/异常边界证据不完整（90 个缺失栈帧、57 个间接跳转、115 个尾跳转、1 个调用环）。静态 RAM 诊断 17888 字节、已知调用栈合计 2520 字节；不能据此宣称 RAM 安全或正式发布验收通过。

## 未验证与剩余限制

需要实机/HIL 验证：TAU804M 冷启动、星历分块注入、定位和 GPSBDS 模式切换。未烧录、未部署、未创建版本发布包。历史型号 2 的配置不会自动迁移为 TAU804M，升级后的旧型号配置明确停用辅助定位。
