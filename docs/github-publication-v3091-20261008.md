# V3.091 GitHub 提交说明（2026-10-08）

本次按用户要求暂存当前固件仓库全部可提交改动，并提交至 linkais21/A300-N32L406 的 main 分支。
源码范围包括 V3.085–V3.091 的休眠定位、ACC/振动唤醒、AGNSS 注入节奏、0x8103 参数对齐及 RAM 栈证据修复；交付内容包括当前测试候选包和移至 artifacts/旧程序 的历史资料。

提交前对新增/修改的发布资料及 ZIP 内容检查个人路径和敏感文件。历史源码中唯一疑似 Device Key 是 test_sensitive_values_are_never_echoed 的合成拒绝回显夹具，不是设备实值。
个人用户目录统一替换为 <USERPROFILE>；涉及 132 个路径记录（含 ZIP 成员与对应展开文件），228 个文件同步更新了路径或校验引用。原件保存在本地被 Git 忽略的 build-v3091-validation/publication-originals/，未上传。
更新后的 SHA-256 与文件长度用于标识脱敏资料副本；原始构建记录仍可从本地备份追溯。未改写构建结果、测试结论或版本放行状态。

验证了 453 个烧录/OTA/ELF 等载荷保持逐字节一致，全部处理后的 ZIP CRC 正确；V3.091 全文件 manifest 与 ZIP/展开目录一致。473 个源码输入指纹仍匹配既有验证记录，可复用 212 项 host 测试及构建/发布门禁结果。

V3.091 仍是 VALIDATION_TEST_CANDIDATE，release_approved=false，精确镜像需要实机/HIL 验证。提交与上传不等于正式版本放行、部署或设备烧录。

.gitattributes 将 artifacts 下的交付资料设为 -text，避免 Git 的 CRLF/LF 自动转换改变文件哈希；对本次暂存的产物重新应用该属性，并核对 Git blob 与本地文件逐字节一致。

源码及本轮文档的暂存差异通过 git diff --check。全范围检查另发现 7 个历史产物文件含原始 patch/diff 空行标记或行尾空白，按原始证据保留，未批量格式化；详细结果保存在本地 build-v3091-validation/staged-diff-check.txt。
