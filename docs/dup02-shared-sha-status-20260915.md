# DUP-02：App SHA 共用状态复核

2026-09-15，针对 `build/quality-audit-20260912/REPORT.md` 的 DUP-02。

## 结论与范围

9 月 12 日审计描述的是历史源码；当前工作树已完成 App 内 SHA-256 共用。
`src/sha256.c`、`include/sha256.h` 和向量测试均已纳入 Git，相关实现见提交
`6eab8e6`，此前实施记录见 [9 月 13 日记录](stability-rx-sha-20260913.md)。
本次仅补充状态记录和复验结果，不重复改写安全校验核心，也不改动工作树已有的 FOTA 等优化。

- `src/fota.c` 与 `src/agnss_storage.c` 均调用 `sha256_init/update/final`。
- `Makefile` 的 App 源文件列表包含 `src/sha256.c`。
- context 由调用方局部持有，无全局 SHA 工作区；两类业务保留独立上下文。
- `bootloader/src/image_verify.c` 保留自身 SHA 实现和独立链接；符合原审计允许的镜像边界。
- 包哈希、AGNSS payload 哈希、CRC、签名及持久化格式未因本次复核发生变化。

因此 DUP-02 的“App 内两套实现”代码整改已完成；硬件和资源验收不能仅据此关闭。

## 本次自动验证

在固件仓库根目录执行：

```powershell
python tools/tests/test_sha256_shared.py
python -m pytest -q -p no:cacheprovider tools/tests/test_agnss_snapshot.py tools/tests/test_agnss_storage.py tools/tests/test_fota_platform_flow.py tools/tests/test_fota_verify_scan.py tools/tests/test_firmware_signature.py tools/tests/test_platform_trust_anchor.py tools/tests/test_bootloader_platform_contract.py
git diff --check
```

SHA 实际 C 核心与 Python hashlib 对照：181 个摘要通过，覆盖空消息、abc、
55/56/63/64/65 字节、更多块边界、大数据、多种更新块长度、零长度更新和双 context 交错。
定向 pytest：22 passed，覆盖 AGNSS 存储/快照、FOTA 流程与校验拒绝、真实签名和平台
信任锚、Bootloader 契约。其中部分 Bootloader 契约测试为静态检查，不等同于目标执行。

这是现有行为的复验，没有新增缺陷修复或本轮 RED→GREEN 声明。

## 资源证据及剩余验证

已核对历史 `build/stability-sha-20260913/comparison.json`：SHA 合并阶段 App BIN
从 105,800 B 降至 105,160 B，差值 640 B。该数值属于历史同条件对照，
不是本次节省量，也不是当前含其他优化工作树的资源测量。
历史记录中 SHA 合并未增加静态 RAM，仍保留栈上的 256 B 消息调度数组；当时
RAM/release gate 未通过，不能将这些历史结果解释为当前发布验收通过。

本轮只修改文档，未重新构建固件、运行 RAM/release gate、生成发布包或烧录。
当前整机最大栈、主循环/IRQ 延迟、实际 OTA 合法/篡改包与断点恢复、AGNSS 注入
仍需要实机/HIL 验证；生产部署未验证。未提交、推送或修改归档固件。

本轮实际触碰：本文件，以及原审计报告 DUP-02 下的复核状态链接。
