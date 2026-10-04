# 华大 AGNSS 对接缺口记录

日期：2026-09-30

## 当前结论

当前 N32L406 固件已经接入华大 `F1 D9` 帧格式、在线 HTTP 下载、帧校验、注入前冷启动和逐帧 ACK 状态机。Host 回归与固件构建已通过；TAU804M UART 的真实 ACK、服务下载和定位效果仍需实机/HIL 闭环确认。

## 根因

1. 缓存注入路径原先直接把 UART 写成功当作完成，未等待 TAU804M ACK；现已改为逐帧等待 ACK，并在 NAK/超时后释放 pending 状态，避免缓存永久卡住。
2. 注入前原先没有实现华大 A-GNSS 应用指南 V1.4 要求的冷启动命令；现已加入：
   `F1 D9 06 40 01 00 01 48 22`。
3. AID-TIME 仅在有保留 UTC 时发送，AID-POS 仅在定位标志和坐标范围有效时发送；尚未证明位置年龄和精度小于指南限值。保留 UTC 只接受严格晚于当前保留值的时间，避免时间回退；上游时间是否超前及文档要求的绝对 UTC 误差仍须实机测量。
4. 在线请求固定使用 `HD_BDS.hdb` 和默认 IP `39.108.211.33`；本轮产品确认当前设备为单北斗且该 IP 仍为授权服务，因此文件类型保留为 `HD_BDS.hdb`，IP 暂不改动。应用指南仍建议正式环境使用域名，IP 的持续有效性需部署侧继续监控。
5. 华大资料之间存在 ACK 语义冲突：A-GNSS 应用指南要求星历帧等待 ACK；ALLYSTAR 二进制协议规范 V2.3.6 对非 CFG 消息的 ACK 描述不同。当前在线代码选择等待 ACK，缓存代码没有等待 ACK，必须先用实际 TAU804M 确认。

## 本轮最小修复文件

本轮实际修改：

- `include/agnss_vendor.h`
- `src/agnss_huada.c`
- `src/agnss_manager.c`
- `src/agnss_online.c`
- `src/gps.c`
- `tools/tests/test_agnss_online.py`
- `tools/tests/test_agnss_vendor_stream.py`
- `tools/tests/test_agnss_scheduler.py`
- `tools/tests/test_agnss_snapshot.py`
- `tools/tests/test_gps_ntp_apply.py`
- `tools/tests/test_gps_retained_clock.py`
- `docs/agnss-huada-gap-record-20260930.md`

不计划顺手重构 AGNSS 存储、HTTP 客户端或 GPS NMEA 解析。

## 需要产品/实机确认的问题

1. **ACK 策略（已按文档落实）**：应用指南要求 AID-TIME、AID-POS、AID-PEPH-GPS/BDS 按顺序逐条发送并等待 ACK；正确数据帧会返回 ACK。代码已按此实现，TAU804M UART4 实际 ACK/NAK 仍需抓包确认。
2. **冷启动策略（已确认允许）**：每次 AGNSS 注入前允许发送 `F1 D9 06 40 01 00 01 48 22`，以清理旧辅助数据。
3. **在线数据类型（已确认）**：当前为单北斗定位模组，使用 `HD_BDS.hdb`，只接受 BDS `0x33` 星历帧。
4. **服务地址（已确认）**：`39.108.211.33` 仍是当前授权服务；本轮不改地址。文档建议域名访问，实际 IP 契约需部署侧持续确认。
5. **缓存策略（未要求扩大）**：应用指南只要求下载到主控本地并发送给模组，未要求写外部 Flash 或跨重启复用；本轮不新增落盘。
6. **可信 UTC（已确认约束）**：以现有 EC800M NTP（`ntp.aliyun.com`）同步结果作为可信 UTC 锚点，GNSS 仅在时间严格更新时刷新保留时钟；任何较旧时间拒绝写入。AID-TIME 只在有保留 UTC 且字段有效时发送，目标是满足文档 ±3 秒门限。实时时钟相对真实 UTC 的绝对误差仍需现场校准验证。

## 已完成验证

以下 host 回归全部通过：

- `python tools/tests/test_agnss_online.py`
- `python tools/tests/test_agnss_vendor_stream.py`
- `python tools/tests/test_huada_ack_trial.py`
- `python tools/tests/test_gps_agnss_ack.py`
- `python tools/tests/test_agnss_scheduler.py`
- `python tools/tests/test_agnss_snapshot.py`
- `python tools/tests/test_gps_ntp_apply.py`
- `python tools/tests/test_gps_retained_clock.py`
- `python tools/tests/test_ec800m_ntp_sync.py`
- 固件构建：`mingw32-make.exe -j2 all`（退出码 0）

构建结果：FLASH `105900/106496`（余 596 字节），RAM `19060/24576`；Flash guard 报告 `LOW_HEADROOM`，需纳入后续容量风险跟踪。

## 2026-09-30 HIL 烧录包与容量复核

- 最终镜像身份：`T360-A300_406_20260930140455,V3.080`，版本计数 `3080`。App HEX 地址从 `0x08006000` 开始。
- HIL 包：`artifacts/A300-406-V3.080-AGNSS-ACK-HIL-20260930.zip`；包内 BIN、HEX、容量报告、清单和现场验证说明已做长度、SHA-256 和 ZIP 完整性校验。未覆盖旧包，未烧录。
- 相同源码的隔离容量试验：`-finline-limit=64` 使用 `106288` 字节，比当前多 `388` 字节；`-finline-limit=512` 使用 `105776` 字节，比当前少 `124` 字节。512 方案改变全程序代码生成与栈路径，而 RAM/栈证据仍未闭合；收益不足以解决低于 4 KiB 的余量告警，本轮不改构建参数、不把试验镜像交付烧录。
- 最终 `release-guard` 通过，`ram-guard` 失败：11 个缺失帧、10 个间接转移、33 个尾转移、2 个内部调用尚未闭合，首个未闭合根为 `ADC_IRQHandler`。该镜像仅供专用设备 HIL 测试，不能当作正式发布通过。
- `test_flash_gate_build.py` 的隔离夹具在导入 `map_ram_guard.py` 时缺少未跟踪的 `exception_stack_guard.py`，8 个用例在夹具阶段失败；实际固件 `flash-guard` 已通过。夹具问题需单独修复后重跑。

## 2026-09-30 TAU804M 原始 NAK 取证

取证来源：`ReceivedTofile-COM12-2026_9_30_15-53-09.DAT`，固件身份 `T360-A300_406_20260930154352,V3.080`。本次一条在线注入记录：HTTP 200，接收 `3376/3376` 字节；冷启动到首帧发送相隔 5 ms，首帧发送到收到响应相隔 45 ms。

- 首帧 TX：`F1 D9 0B 33 CC 01 ... 10 27`，共 468 字节、负载 460 字节，双累加校验正确。负载包含 5 颗 BDS 卫星（SV 1、2、3、4、6）；周数 1082、toe/toc 284400 秒、health 均为 0，未见明显过期周数或坏健康标志。首帧 SHA-256：`8add39d240f249ebde3cf0d8e2514273ebbad24c656add1020bc3eb82123866f`。
- RX 原文：`F1 D9 05 00 02 00 0B 33 45 6F`，帧校验正确，明确是对 `0B/33` 的 NAK。`ACK-NAK` 只携带被拒绝消息的组/子 ID，不携带具体错误原因。
- 注入结果 `tx=1 ack=0 result=0`，其余星历帧没有发送；后续定位有效不等于 AGNSS 成功。
- 未确定根因。A-GNSS 应用指南描述冷启动后会输出两条 NMEA 标识语句，而当前代码仅隔 5 ms 就发送首帧；需做只改变冷启动后等待时间的受控 HIL 对比，或向华大确认 TAU804M 固件对该 AID-PEPH-BDS 帧及 NAK 的具体要求。不能仅凭本次 NAK 认定星历格式或时序哪一项错误。

这些测试不能替代 TAU804M UART/HIL 验证。当前未验证冷启动命令的实机执行、缓存 ACK、真实服务文件下载、AID-TIME 绝对 UTC 误差是否在 ±3 秒内、AID-POS 误差是否小于 75 km、首次定位耗时和断网恢复。

## 修复原则

本轮按“先复现根因、再增加失败回归、最后做最小实现”完成。已运行受影响的 host 测试、`git diff --check` 和相关固件构建；未提交、未推送、未烧录。后续只需安排 TAU804M 实机/HIL 抓包与定位指标验证，暂不扩大代码优化范围。
