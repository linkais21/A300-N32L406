# OTA 进度实机验证：V3.046 → V3.047

按用户最新要求交付两个版本，每版均含 Combined HEX、Combined BIN 与 OTA BIN；两版功能相同，版本递增用于验证远程升级。目标 N32L406CBL7，产品 A300-406。

## 建议操作

1. 记录需要保留的设备配置。烧录 SWD-Combined-V3046.hex（推荐，HEX 自带地址）；若使用同名 BIN，起始地址必须为 0x08000000，两者二选一。
2. Combined 含新 Bootloader、一次性工厂初始化请求及 App。首次启动会清理配置 A/B、BCR、OTA 检查点和授权记录；完成初始化后普通重启不会重复清理。恢复必要参数，确认 V3.046 联网上线。
3. 将 OTA-A300-406-V3047.bin 上传现有 FOTA 平台，型号填 A300-406，版本号填 3047，显示版本 V3.047。使用平台现有分离式签名流程。不要上传 Combined 或原始 App BIN。创建测试设备升级任务后按现有开机检查流程验证；常规轮询为 6 小时。
4. 串口 115200、8N1，观察 download progress=0% 到 100%，重启后 install progress 到 100%、state=trial-ready，再确认启动 V3.047。安装百分比按真实已提交字节计算，跨 10% 区间打印，可能显示 11%、21% 等。
5. 安装 100% 表示已安装并准备试运行，不表示 TRIAL 确认/LKG 晋升已经完成。既有流程约 30 秒后确认并软件复位一次，随后检查版本、配置保留、上线、GNSS 和 HEALTH。

OTA 文件为 32 B 包头加 105208 B App，总长 105240 B。Combined BIN 长 129784 B。两版 OTA 都是 App-only，保留配置，不更新 Bootloader。
现有 V3.045 可直接 OTA 到 V3.046 或 V3.047，但旧 Bootloader 无法显示新增安装百分比。要完整验证进度，请采用上述先烧录 V3.046 再 OTA V3.047 的顺序。已烧录 V3.047 的设备不能用同版本包验证升级。

## 验证状态

两版分别执行 python build/build_ota_progress_3046.py、python build/build_ota_progress_3047.py，均退出 0。每轮 22 项定向测试通过，包含真实安装进度、串口超时、FOTA 下载/续传/掉电、Boot 恢复、Flash 布局、GNSS 分类和包格式。Boot/App 构建、版本契约、必要帧预算、libc 检查、CRC/SHA256、镜像边界和 HEX/BIN 一致性通过。
完整 make release-gate 两版均退出 2：release-guard 通过，RAM gate 因 incomplete stack evidence 拒绝。App 静态 RAM 17896 B，已知主调用帧链 2528 B，必要预算剩余 4152 B；不能替代完整库/IRQ/间接调用栈证据。因此 release_approved=false，本包为实机/HIL 验证版，未作为正式量产版放行。
需要实机/HIL 验证：新 Bootloader 串口与 Flash 时序、安装全过程/掉电恢复、TRIAL 确认、配置保留、长期 RAM 水位和 GNSS 丢句。本次未烧录设备、上传平台、部署或发送设备命令。
历史日志已证明 V3.044→V3.045 成功；首次 401 后续恢复，历史根因未裁定。若再现 401，请保留日志；本次未更改平台鉴权。

## 文件与追溯

ZIP 含六个固件文件、本说明与 SHA256SUMS.txt。目录另含各版本 ELF/MAP、manifest、源码指纹，以及 validation 下的构建/测试日志和栈证据。旧版本归档未覆盖。
本轮交付修改 release_identity.json、include/config.h、include/build_version.h、tools/tests/test_release_identity_contract.py、tools/release_guard.py 的版本相关内容，最终为 V3.047；README 记录本次双版本例外。打包脚本和归档记录在 build、artifacts 下。保留此前 OTA 进度实现与其他工作树修改，未提交或推送。
