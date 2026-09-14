# 实机验证包：SWD V3.044 → OTA V3.045

目标 MCU：N32L406CBL7，A300-T9 / A300_406。2026-09-14。
用户请求生成的实机/HIL 验证包，release_approved=false；完整 RAM/release gate 未通过，不能作为量产放行。

## 使用文件

| 文件 | 用途 | 设置 |
|---|---|---|
| SWD-Combined-V3044.hex | 推荐烧录文件，含 Bootloader、一次性初始化请求、V3.044 App | 目标 N32L406CBL7，HEX 自带地址 |
| SWD-Combined-V3044.bin | 与上述 HEX 相同的完整镜像，二选一 | 起始地址 **0x08000000**，129784 B |
| OTA-A300-406-V3045.bin | 上传 FOTA 平台的升级文件 | 产品/型号 **A300-406**，版本号 **3045**，显示版本 **V3.045**，105240 B |

不要将 Combined 当 App-only 烧到 0x08006000，也不要把 Combined 或 App 原始 BIN 当作 OTA 文件上传。OTA 包是 32 B A300 包头加 105208 B App，使用现有平台分离式签名流程；本地文件不是附带私钥签名的完整下载响应。

两版功能一致，都包含 RAM 函数边界调整和 GNSS 分类计数；递增版本用于验证远程升级流程。两版 Bootloader 相同，保留 V3.043 冷启动 Flash 识别重试。V3.042/V3.043 旧归档未覆盖。

## 验证步骤

1. 用 SWD 烧录 V3.044 Combined HEX 或 BIN，完成校验后启动设备。**此 Combined 沿用当前工厂初始化流程，首次启动会清理配置 A/B、BCR、OTA 检查点及授权记录；验证设备上需要保留的配置应事先记录。** DONE 后正常重启不会重复初始化。
2. 串口 115200、8N1，确认启动 V3.044、Flash 识别、4G/JT808 上线与 GNSS 定位。记录 HEALTH 的 STK_PEAK/RAM_GAP/F 和 GPS 的 QDROP/LDROP/OREF。
3. 上传 **OTA-A300-406-V3045.bin**，填写型号 A300-406、版本号 3045，为测试设备创建升级任务。任务就绪后按现有流程重新启动测试设备，使其执行开机检查；常规轮询周期为 6 小时。
4. 预期日志依次出现检查接受 version=3045、下载、verify/authorized/pending，然后启动 V3.045。TRIAL App 运行约 30 秒后确认并主动复位一次属于现有流程，随后应稳定运行。
5. OTA 是 App-only，不携带工厂初始化请求；检查设备身份、服务器/上报参数及其他测试配置保留，继续观察 GNSS、网络与 RAM 水位。

**FOTA 401 尚未关闭。** 前轮日志及只读在线检查均得到 401；线上入口返回 gunicorn HTML，而本地后端为 Spring Boot。若本次检查仍打印 `HTTP response status=401`，下载尚未开始，需要先修复平台入口/鉴权契约一致性；本包未擅自增删鉴权。本次没有上传平台、创建任务、烧录设备或部署服务。

## 资源与验证结果

两版均为 App 105208 B（剩余 1288 B），静态 RAM 17896 B，已知主调用帧链 2528 B。必要预算剩余 4152 B，完整库/IRQ/间接调用/堆证据仍不完整，**release-gate 退出 2，未放行**。不能据此宣称实机 F 已清零或丢句已消失，需要实机/HIL 验证。

已 fresh 执行 Boot/App 构建、真实平台签名验证、Boot 首次初始化/识别重试/失效拒绝测试、Flash 布局、OTA 包/流程/掉电/调制解调器交接、GNSS 丢句分类回放、串口 F39、Combined 流程测试。两版版本契约、必要帧预算、libc parser、OTA 头/长度/CRC、公钥嵌入、Combined HEX→BIN 字节一致性与 SHA manifest 均通过。完整命令及退出码在 validation/commands.json。

首次预检在旧 `test_internal_flash_layout.py` 失败：仍要求 _sbrk 引用 _estack，与已实施 RAM-02 堆硬上界不一致。已改为核对 _heap_limit 链接契约并执行真实 _sbrk 越界拒绝测试；重跑通过。首次失败日志保留于工作区 build/hil-ram01-20260914/，未用后续成功掩盖。未修改 _sbrk 实现或降低校验。

SHA256SUMS.txt 用于直接使用文件校验。V3.044/、V3.045/ 含 ELF/MAP、manifest、源码指纹；validation/build-evidence/ 保留相应原始最终 LTO .su 和报告，供后续复核。交付 ZIP 仅含上述三个直接使用文件、README、SHA256SUMS.txt。
