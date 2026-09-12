# A300_406：V3.036 SWD → V3.037 OTA 验证包

本包面向 N32L406CBL7，修复 OTA 信任公钥错误。两版功能代码一致，版本标识分别为 V3.036/3036、V3.037/3037。
已完成编译、发布门禁、签名回归、包结构及哈希检查；尚未执行实机烧录或本次 V3.037 的远程升级。

## 1. 先通过 SWD 烧录 V3.036

- 文件：`SWD-Combined-V3036.bin`，130352 字节。
- 起始地址：**0x08000000**。
- 内容：Bootloader + 填充区 + App；App 已位于 0x08006000 偏移对应位置。
- 使用已有 N32L406 烧录工具执行写入和回读校验，再复位运行。
- 必须使用这个完整包，不要仅烧 App，否则旧 Bootloader 的错误公钥可能仍然保留。
- 不需要清空外部 SPI Flash 或设备配置；保留现有服务器、设备身份等参数。
- 串口检查启动版本为 `V3.036`，并出现 `key=FOTA-PLATFORM-P256`、`[4G] ready`。

## 2. 再通过平台升级 V3.037

- 上传文件：`OTA-A300-406-V3037.bin`，105808 字节。
- 平台设备型号：**A300-406**。
- 版本号：**3037**；显示版本：**V3.037**。
- 包格式为 32 字节 A300 包头 + App。平台上传流程生成分离式签名；无需用户本地签名。
- 为正在运行 V3.036 的设备创建升级任务。任务配置完成后复位设备，以触发开机检查。
- OTA 平台地址沿用设备现有配置，不是 JT808 主/备服务器地址。
- 不要将 SWD Combined 文件上传为 OTA，也不要把归档旧 V3.035 当作本次目标。

## 3. 实机验收

串口应依次出现以下关键阶段（中间允许有其他日志）：

```text
check result=accept version=3037 size=105808
download progress=100% bytes=105808/105808
install progress=authorized version=3037
install progress=pending version=3037
install progress=reboot version=3037
... V3.037
```

目标 App 持续运行约 30 秒后会提交 TRIAL→ACTIVE，并主动复位一次；这是当前确认流程。
之后应继续运行 V3.037、恢复正常联网，不能反复重启或回到旧版本。
保留从 SWD 后首次启动到 OTA 后稳定联网的完整串口记录。电源、Flash 安装、看门狗和启动确认需要实机/HIL 验证。

## 4. 文件校验

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| SWD-Combined-V3036.bin | 130352 | 8e0d1250f409b092817a77d20ef60091e7488f6efc08e8eb49c540d85c412905 |
| OTA-A300-406-V3037.bin | 105808 | db571d2c1f16a1053dd27dc7a7a91e85775bb49bb5a20f0e23fe227005c537f6 |

PowerShell 可使用 `Get-FileHash -Algorithm SHA256 <文件路径>` 核对。

## 5. 构建及验证记录

完整原始产物分别归档于上级目录 `V3.036/`、`V3.037/`，包含 ELF、MAP、HEX、BIN 和 `SHA256SUMS-N32L406CBL7.json`。
两个版本均已实际执行并通过：

- `python tools/build_dev_release.py`（指定工作区已安装的 make；强制完整编译 App 和 Bootloader，无构建警告）。
- `make release-gate`：版本/身份门禁、RAM、栈、libc 解析器及真实平台公钥验签检查。
- `python tools/tests/test_dev_release_manifest.py --manifest <各版本清单>`。
- `python tools/tests/test_release_identity_contract.py`、`python tools/tests/test_feature_guards.py`。
- 全部产物哈希、OTA 包头/CRC、Combined 拼接位置以及正确公钥字节检查。

此外，本轮通过 OTA 流程/断点续传、串口二进制接收与通道交接、Bootloader 拒绝错误镜像/恢复等定向回归；
包括 25715 个 checkpoint 掉电切点、4803 个授权记录切点和 90 个 LKG 操作切点。
真实平台签名回放采用已保存的 V3.035 签名样本验证密码学和安装授权流程，不能替代待上传 V3.037 的平台签名及实机验收。

App 静态 RAM 为 17820 字节，FOTA 状态机审计栈帧为 776 字节。两版本使用相同的修正后 Bootloader。
源码工作树保留原有未提交修改，本轮新增版本更新、审核后的版本指纹更新及不影响行为的参考注释调整；未推送、未部署、未发送设备指令。
