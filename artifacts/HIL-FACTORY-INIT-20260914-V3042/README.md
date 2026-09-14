# V3.042 Combined 首次启动测试包

目标：A300-T9 / N32L406CBL7。仅供本次用户要求的实机/HIL 测试。
文件位于 `V3.042/`，旧测试包未覆盖。

## 烧录

优先使用 `V3.042/Combined-N32L406CBL7.hex`（自带地址），或
`V3.042/Combined-N32L406CBL7.bin`（起始地址 `0x08000000`），二选一。
使用支持 N32L406CBL7 的烧录器，先擦除 MCU 内部 Flash，再写入完整 Combined，
执行写后校验，复位运行。不能只写 App 来验证此次首次初始化功能。
手动烧录无需运行附带 PowerShell 包装器；该包装器的实际编程器兼容性尚需实机验证。

如分开烧录：Bootloader BIN 地址 `0x08000000`，App BIN 地址 `0x08006000`。
保持 MCU 停止，完成两份镜像写入和校验后再复位；建议直接使用 Combined。
不要把 Combined 当作 OTA 包或写到 App 地址。

## 预期结果

每次完整 Combined 烧录会恢复内部 `0x08005800` 的 pending 请求。
首次启动将清除外部配置 A/B（0x000000、0x001000）、BCR A/B
（0x100000、0x101000）、OTA 检查点 A/B（0x102000、0x103000）、
OTA 授权 A/B（0x104000、0x105000）。配置会恢复默认服务器，设备身份由 App 重新生成。
Factory、LKG、candidate、盲区、AGNSS 不属于此次清理范围。
正常复位和 App-only/OTA 不重新请求清理。

1. 串口设置为 115200 / 8N1，烧录前打开接收。
2. 确认版本 V3.042、`[BOOT] ready`、`JEDEC=684015`、`[4G] ready`、
   `[808] ch0 ONLINE`。
3. 检查 `[GPS]` 的 RX/GGA/RMC 大于 0，CS/FMT 为 0。室内 GPS=0 只说明尚未定位，
   室外有效定位需另测。FOTA HTTP 401 属于设备 Key 配置问题，单独记录。
4. 正常断电重启一次，确认仍能启动和上线。
5. 保存串口日志用于复核，分享前脱敏 IMEI、ICCID、位置、服务器和凭据。

## 验证与限制

Bootloader/App 全量构建、Bootloader 容量守卫、身份、公钥、初始化、BCR fail-closed、
Flash 布局、产物、自检及 DryRun 测试已执行。命令及退出码保存在 `V3.042/validation/`。
App 占用 105160/106496 B，余量 1336 B。
`release-guard` 通过；`release-gate` 因现有 RAM 门禁失败，保留区估算
3696 B 小于 4096 B，完整栈/堆/异常证据未闭合。清单明确标记 `release_approved=false`。

本包未烧录实机，所有启动、联网、定位及掉电行为需要实机/HIL 验证。
当前实现会拒绝未知 completion 值；DONE 字写入中断若留下部分写入值，会进入恢复等待，
不能声称已保证该掉电切点自动收敛。完整断电鲁棒性尚未验收，勿用于批量生产。

SHA256SUMS-N32L406CBL7.json 校验固件；ELF/MAP、源码指纹和关键 Bootloader 源文件
保留在包中用于追溯。附带 OTA 文件仅更新 App，不能把旧 Bootloader 升为此次版本。
