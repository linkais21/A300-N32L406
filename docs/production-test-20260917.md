# 标准固件生产测试补齐（2026-09-17）

本轮按用户授权合入已有数学/日志/毫米量化优化，并补齐工具现有测试项的固件接口；TTS、RS485 明确不测试。不扩展先前报告建议的 Flash、电池、平台上线、LED 等额外验收项。未提交、推送、部署或烧录，保留用户已有修改。

## 交付

- 工具 V1.6.0：[A300ProductionTester.exe](../../生产测试工具/A300ProductionTester/build-releases/V1.6.0-production-candidate/A300ProductionTester.exe)。同目录包含 README、默认配置、SOURCE_REVISION 和 SHA256SUMS。
- 标准固件候选：固件仓库 `build-production-20260917/a300_firmware.{bin,elf,hex,map}`，按现有 Makefile 构建，没有专用裁剪固件，没有改变 Flash 布局。BIN 是 App 分区镜像，地址仍为 0x08006000，不能当成含 Bootloader 的整片镜像。
- 当前版本标识仍为工作树 V3.054，未分配发布版本。之前 V3.054 交付包不含这些接口，必须核对本候选文件身份与 FACTORYCAP，不能仅凭版本号认定同一输入。
- 初始输入快照：`build-production-baseline-20260917/source-before/`。同目录保存未优化主目录基线构建，未覆盖原有交付包。

## 接口与行为

| 接口/项目 | 实现与安全边界 |
|---|---|
| FACTORYCAP# | VER=1；ACC/GSENSOR/VOLTAGE/RELAY/SOS/GNSS=1；TTS/RS485=0 |
| ACCSTAT# | 独立 50 ms 物理 ACC 去抖；RAW 是外部 ON 归一化值，DEB 用于两次通断验收，HW/LOGIC 仅诊断；不改变业务 500 ms 去抖 |
| GSENSOR# | 直接使用现有有界 I2C 驱动读取 signed XYZ，失败返回 READ_FAILED；未改变 DA218E 地址探测或引脚 |
| STATUS# | 两个 ADC 转换均有效且新鲜时提供整数 mV；真实零伏与转换超时区分，超时不会被当作零伏触发错误断电事件；无有效样本返回 ADC_NOT_READY |
| RELAYTEST,LOW/HIGH/STATUS# | 3000 ms 单次脉冲；重复 LOW 返回 BUSY，不续时；SysTick 独立恢复；脉冲期间拦截 STOP1。MCU/PAD 诊断不替代外部治具人工观察 |
| SOSSTAT# | DOWN/HOLD_MS；工具每轮先观察释放，再观察本轮连续按下，超时失败；不接受历史异步日志或人工确认替代 |
| GNSSSTAT# | 新鲜 GGA 定位质量、完整新鲜 GSV；GPS/BDS 的 GP、BD/GB 和 GN，不重复叠加混合 GN 与独立星座、不重复累加信号带；SEQ 取实际参与统计的最新完整周期时间戳 |
| GNSS 无定位/过期 | RMC V 和 GGA 质量 0 立即撤销有效状态；RMC 不能刷新旧 GGA 的质量年龄；只靠卫星数量不能通过 |
| MODEL/APN | 工具改用现有 MODEL#、APN# 核验非敏感字段，不扩大 PARAM/SMS 响应；APN 凭据只确认写入应答，不以密码明文回读为验收条件 |
| TTS/RS485 | 固定排除，旧订单/全选/单项运行不能启用；不计通过；只有排除项或零实际测试时显示“测试未完成” |

生产命令只在本地调试 UART 分发，不加入 F39 短信/JT808 命令表。F39 断油安全条件保持，业务请求不能延长生产脉冲。生产查询不改持久化布局或参数格式。工具停止查询 5 秒后产测专用 ACC/SOS 高频采样自动停止，重新查询时不会把一直按住的 SOS 当作释放。

GNSS 初始化及唤醒恢复中的既有 PCAS03 配置启用 GSV。是否被当前模组接受、NMEA 突发数据是否丢包以及实际 CN 门限需要实机/HIL 验证。天线电气开短路没有硬件反馈，工具明确不宣称已测该项目。GPS/BDS 外其他独立星座的 GSV 不纳入本产品质量统计。

板级冲突：工作区旧表中的 ACC PA3 与当前原理图/驱动 PA12 不一致。原始 `comm_board/A300-T9原理图.pdf` 及 MCU 图对应 PA12=M_ACC_IN、PA2=M_SOS、PA3=CAR_ADC、PA11=OIL_CTR；本次保持当前映射，未按旧表修改硬件。实际治具仍需按板版本核实。

## 合入优化与容量

采用已有 `firmware_size_trial.py` 的 bounded 数学、毫米量化和 4 条已审查普通日志抑制。错误、恢复和协议诊断日志保留；持久化布局不变。毫米边界是用户同意沿用的优化包行为，不宣称与旧源码逐点等价。

合入前再次执行真实 C 数学回放：25128 点对、12000 连续样本、持久化回归通过；局部最大距离差约 7.65e-9 m。毫米策略与旧规则有 985 点对决策变化，6 条约 69–71 km 轨迹终值变化 0/0/0/+1/+2/+1 m，与已有实验记录一致。回放记录位于 `build/production-math-replay-20260917/`。

| 构建 | Flash 占用 | App 剩余 |
|---|---:|---:|
| 本轮未合优化基线 | 105520 / 106496 B | 976 B |
| 合入优化并补齐产测后的最终候选 | 100820 / 106496 B | 5676 B |

“原来 8000 多字节”来自此前使用覆盖源码生成的优化交付输入，并非本轮开始时的主目录源码。现在优化已合入标准源文件，普通 Makefile 构建即可包含。

RAM：静态 17948 B，已知主调用帧 2496 B，计入二者后余量 4132 B，高于 4096 B 必要间隔 36 B。**ram-guard 仍失败**：78 个缺失帧、51 个间接转移、113 个尾转移、1 个环，缺少完整栈/堆/异常上界。该类别在本轮基线记录已存在；本次未绕过门禁，也不能证明 SRAM 安全或批准量产。

## 实际验证

新增产测模块/relay/GSV 接口测试先在接口不存在时失败；毫米边界在合入前失败；无定位 RMC 撤销状态测试在修复前失败；零实际测试误判成功的 C# 测试在修复前失败，修复后均通过。

固件命令均在 `A300-first/` 执行；下表脚本命令为 `python tools/tests/<名称>.py`。

| 验证 | 最终结果 |
|---|---|
| test_production_test / test_production_relay / test_production_gnss / test_production_adc | PASS；命令、失败、50 ms 去抖、SOS、计时回绕、LOW 不续时、强制恢复、ADC 零值/超时/恢复/过期、GSV 缺包/重复/混合/信号带/校验和/新鲜度 |
| test_at_config_serial_f39 / test_at_config_handoff / test_f39_end_to_end | PASS；真实串口入口及 F39/SMS 链路；本地生产处理器不会被短信/平台命令调用；初次缺新依赖的夹具已补齐后重跑 |
| test_nmea_replay / test_gps_drop_diagnostics / test_gps_tx_bounded / test_gps_ntp_apply | PASS |
| test_mileage_quantization / test_mileage_persistence / test_size_trial / test_adc_power_loss_mileage | PASS；量化测试直接测试标准源码，不再依赖覆盖生成 |
| test_remote_relay / test_relay_sms / test_hardware_bringup_profile / test_feature_guards | PASS |
| test_agnss_snapshot / test_agnss_scheduler / test_jt808_dual_session / test_jt808_params / test_motion_corner_policy / test_corner_blind_zone_replay | PASS |
| 工具 tools/test_protocol.ps1 | PASS；包含实际 MainForm 结果汇总与真实 C 处理器生成的 24 条响应跨端解析 |
| 工具 build.ps1 | PASS；.NET Framework，warnaserror，独立输出目录；源哈希及构建产物校验清单 |
| mingw32-make.exe -s all BUILD=build-production-20260917 | PASS；ARM 编译、链接、ELF/MAP/BIN 容量检查 |
| 同一 make -s release-guard BUILD=build-production-20260917 | PASS；源码发布输入门禁，非完整量产验收 |
| 同一 make -s ram-guard BUILD=build-production-20260917 | FAIL；完整栈证据不足，详见上文 |
| 范围内 git diff --check、构建清单 SHA256、EXE 对应源码哈希核验 | PASS；当前源文件/输出身份记录在 `build-production-20260917/DELIVERY_INPUTS.json` |

工具跨端验证命令（工作区根目录）：

```powershell
python A300-first/tools/tests/test_production_test.py --wire-output A300-first/build-production-20260917/production-wire.txt
powershell -NoProfile -ExecutionPolicy Bypass -File 生产测试工具/A300ProductionTester/tools/test_protocol.ps1 -FirmwareReplies A300-first/build-production-20260917/production-wire.txt
```

## 本轮触碰文件

固件实现：`Makefile`、`include/production_test.h`、`src/production_test.c`、`include/relay.h`、`src/relay.c`、`include/adc_monitor.h`、`src/adc_monitor.c`、`include/gps.h`、`src/gps.c`、`src/hw_init.c`、`src/main.c`、`src/at_config.c`、`src/mileage.c`、`src/jt808.c`。

固件测试/实验工具：新增 `tools/tests/test_production_{test,relay,gnss,adc}.py`；更新 `test_at_config_serial_f39.py`、`test_f39_end_to_end.py`、`test_mileage_quantization.py`、`test_size_trial.py`、`tools/experiments/firmware_size_trial.py`（适配已合入候选，避免重复生成数学 helper）。

上位机：`src/A300ProductionTester.cs`、`src/ProductionProtocol.cs`、`config/a300_tester.ini`、`build.ps1`、`tools/ProtocolTests.cs`、`tools/test_protocol.ps1`、`README.md`、既有匹配报告顶部状态说明。构建脚本支持无 Git 的源目录并记录哈希，只允许新输出目录，保留现有 bin/配置/orders/records。

文档：本文件和 `docs/superpowers/plans/2026-09-17-production-test.md`。构建/回放/快照位于本轮新增 build 目录，不属于已有交付产物覆盖。

## 尚需实机/HIL

逐台治具：串口接线、实际身份/版本、模组/SIM 初始化、GPS/BDS GSV 和天线接收质量、ACC 两次通断、XYZ 响应、电压校准、SOS 释放后保持、断油外部 LOW/HIGH 两轮；故障注入包括拔串口、关闭工具、MCU 复位、驱动读失败、主循环延迟时的脉冲恢复。

优化专项：ARM 数学边界、实际里程/静止漂移及重启保持。内存专项：栈/堆/中断完整证据与实机水位。未执行 GUI 人工操作、真实设备/平台通信、烧录或部署。本候选不是量产批准版本。
