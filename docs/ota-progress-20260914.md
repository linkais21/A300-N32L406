# OTA 日志分析与进度显示调整

输入：工作区 `ReceivedTofile-COM4-2026_9_14_19-14-56.TXT`，30280 B、904 行，SHA-256 `deace54538f7f478a5b7d2eafe8fec7e1453d36a89d678d78fa699261768e8cb`。分析保留原件，报告不复制设备身份、下载 token 或坐标。

## 本次 OTA 结果

**V3.044 → V3.045 已成功完成。**

| 日志行 | 证据与判断 |
|---|---|
| 4–42 | V3.044 上电，第一次更新检查返回 401。这次失败仍真实存在 |
| 144–184 | 再次启动 V3.044，Reset=software；检查经过第二次连接尝试，HTTP 200，接受 version=3045、size=105240 |
| 186–212 | 外部候选区准备/擦除到 106496 B；不是内部 App 安装 |
| 243–687 | 下载进度每 5% 一条，共 20 条，到 100%、105240/105240 B |
| 688–695 | verify-start → authorized → pending → reboot。生产代码只有通过包校验、签名及授权记录提交才会到达这些状态 |
| 699–750 | 启动 V3.045，并重新 JT808 ONLINE。首个新版启动期间有资源忙导致检查暂缓 |
| 764–816 | 又一次 software reset 后仍是 V3.045，更新检查 HTTP 200、parsed=1 update=0，重新 ONLINE。这里旧日志的 reject 代表无更新，不是升级失败 |
| 835–904 | 新版连续四个健康采样均 F=0，READY/REG=1/GPS=1，最后 uptime=240 秒 |

下载后的两个 software reset 与“OTA 安装重启 + TRIAL App 约 30 秒后确认并复位”的既有流程一致。由于原日志缺逐行时间戳和显式 TRIAL-confirm 日志，不能独立证明每次 software reset 的唯一触发源；下载前的 software reset 也不能归因于 OTA 安装。全文件未见 watchdog/HardFault 复位打印。

配置从下载前到两次新版启动都为 `loaded v4 slot A gen=4`，可见参数一致，有配置保留证据；没有逐字段导出，不能宣称所有配置已完整比较。初始工厂启动使用默认配置与 Combined 初始化流程相容。

前轮 401 在本次后续启动中已不再阻断升级，不能继续说“当前 OTA 完全不可用”；但未取得平台变更记录，401 的历史根因仍未裁定。本轮未访问/改动平台。

## RAM 和 GNSS 结论

本次共 7 条 HEALTH，均 HEAP_USED=0、STK_PEAK=2544、RAM_GAP=4136、F=0；相对旧 V3.043 的 2592/4088/F=1，已有实机改善证据。但健康采样没有覆盖下载/验签最深路径（重启还会重置水位），而且仅约数分钟新版运行，不能代替完整栈预算和长稳验收。

V3.044 最初健康采样 DROP=QDROP=120，之后保持；V3.045 最终启动 DROP=QDROP=160，四次采样保持。全部 LDROP=0、OREF=0，CS/FMT=0。**本日志记录到的软件丢句可归因于队列满，不是超长路径；未观察到硬件 OREF。** 不能排除没有被观测的硬件丢失。主要计数已在首次健康采样前产生，后续样本未增长，优先定位启动/联网/NTP 等期间主循环未及时消费两槽 NMEA 队列；本轮不通过扩大缓存或 ISR 解析来掩盖问题。

## 已实施的显示调整

- App 保留下载每 5% 的百分比与真实已接收字节，补充准备完成后的 0%/续传起始进度。
- 外部候选区擦除改为 `[FOTA] prepare erase=...`，避免误称内部安装。没有隐藏通信异常或删除底层诊断。
- Bootloader 新增真实安装进度：仅在内页擦写、两次读回校验和 BCR 进度提交成功后推进；每跨过 10% 区间输出一次，数值按实际已提交字节计算，可能显示 11%、21% 等。
- 只有最后 TRIAL 状态成功提交后才输出 100%、state=trial-ready。整包已经写完、仅待 TRIAL 提交的恢复场景也不会提前打印 100%。100% 表示镜像已安装并准备试运行，不表示试运行确认/LKG 晋升已完成。
- USART1 PA9/AF4、115200 TX，输出无堆分配、无 printf；等待 TXDE/TXC 有固定上限并服务看门狗。串口输出失败后禁用本次启动后续输出，不改变安装返回结果。未修改其他引脚资源。

预期示例（百分比以实际长度计算）：

```text
[FOTA] prepare erase=106496/106496
[FOTA] download progress=0% bytes=0/105240
[FOTA] download progress=50% bytes=52736/105240
[FOTA] download progress=100% bytes=105240/105240
[FOTA] install progress=verify-start bytes=105240/105240
[FOTA] install progress=authorized version=...
[FOTA] install progress=pending version=...
[FOTA] install progress=reboot version=...
[FOTA] install progress=0% bytes=0/105208 state=writing
...
[FOTA] install progress=100% bytes=105208/105208 state=trial-ready
```

旧 Bootloader 不会因 App-only OTA 自动升级。因此新安装输出必须由含新版 Bootloader 的 Combined 烧录后生效；现有 V3.045 设备仅 OTA 更新 App 时，下载显示会更新，但安装阶段仍受旧 Bootloader 能力限制。

## 验证与交付策略

定向测试记录在 `build/ota-progress-20260914/tests.json`：12 项脚本通过，包括真实 install_resume 的正常、续传、写入失败、BCR 失败、最终提交失败，UART 正常输出/TXDE 卡死/TXC 卡死，以及 App 进度、FOTA 流程/续传/掉电、Boot 失效拒绝/非法向量恢复/LKG 掉电/平台约束/Flash 探测。补充“已全部写入但 TRIAL 提交失败”测试曾 RED，修复后 GREEN。

独立复审无剩余阻断项；另在 test_fota_resume.py 补充并通过非零续传进度断言（4096/13000 B 显示31%）。最终 Boot MAP 静态容量检查通过；git diff --check 退出0。Boot静态容量检查不代表其运行时栈验收。

初始 install 测试有主机链接桩不完整问题，补齐后才获得进度缺失的预期 RED；App 进度用实际 FOTA 回放得到 RED→GREEN。最初弱诊断实现触发既有禁止弱硬件钩子测试，最终改为明确链接的硬件实现，仅在 host 测试提供桩，平台规则没有放宽。

App/Boot 均使用现有 ARM 工具链，在独立 `build/ota-progress-20260914/app`、`boot` 构建。App 105208 B、静态 RAM 17896 B、已知帧链2528 B，与 V3.045 一致；Boot BIN 跨度22556 B包含 0x5800 初始化请求，不能把这个跨度全部视为可执行代码大小。输出 UART 和 Flash 并行硬件时序仍需要实机/HIL 验证。

`make release-gate BUILD=build/ota-progress-20260914/app` 退出2：release-guard通过，RAM gate因 incomplete stack evidence拒绝。没有降低4096 B门限、删门禁或宣称正式版。版本号本轮不更改、旧归档不覆盖，独立构建仅为诊断产物。

用户交付偏好已写入 README：**之后每次只递增一个版本，同时给出该版本的 Combined 烧录固件与 OTA 包，不再为演示升级而同时制作两个新版本。** 正式发布仍需要完整门禁和验收；下一次打包不能把“同一版本两种文件”误写为“已获正式发布批准”。本轮未生成新版本发布包、未烧录、未上传平台、未提交或推送。

本轮源码改动：src/fota.c，bootloader/Makefile、include/image_install.h、src/image_install.c，新增 src/boot_progress.c；三项新测试、三个既有 Boot 测试桩及 test_fota_resume.py 的续传显示断言；README、本报告和执行计划。保留所有之前的工作树修改。
