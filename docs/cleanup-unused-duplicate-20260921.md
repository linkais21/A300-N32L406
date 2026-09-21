# 2026-09-21 固件无效与重复代码清理结果

本轮安全清理已完成。以任务开始时的未提交工作树为基线，同配置独立构建，
Flash 净减少 **516 B**，App 余量由 **164 B 增至 680 B**；静态 RAM 减少 **20 B**。
定位阈值、协议字段、配置格式、Flash 布局和版本身份不变，未关闭功能或日志。
未提交、打包、烧录、部署或覆盖原交付包。

## 审核及清理范围

盘点 src 下 57 个自有 C 模块及配套头文件，对照生产引用、测试、启动汇编和构建结果。
最终扫描覆盖 906 个函数定义；单引用候选已分类，没有剩余未解释候选。
标识符扫描是审查辅助，不是不存在任何死代码的形式化证明。
SDK/第三方库未机械清理，ISR、启动/libc ABI、诊断和实际测试接口、持久化兼容标记及安全恢复路径保留。

删除以下 13 个无实际调用的旧接口及声明：

- ec800m_dma_rx_complete：空回调。
- jt808_get_heartbeat_s：未使用 getter。
- cfg_factory_reset、cfg_set_server、cfg_set_report_interval、cfg_set_mileage：旧配置入口；实际 F39/JT808 配置、恢复默认和里程持久化路径保留。
- spi_flash_erase_chip：未使用整片擦除；实际扇区擦除、校验、超时和 owner 机制保留。
- i2c_accel_detect_vibration、i2c_accel_is_moving：停用检测器及专用状态；活动工作模式检测器保留。
- hw_restore_after_stop2：无调用整套重初始化包装；实际休眠恢复路径保留。
- agnss_storage_data_base、fota_on_data、fota_authorization_clear：旧访问/包装入口；真实接收、授权提交读取、检查点清理保留。

另删除只写未消费的唤醒缓存、无引用私有宏。重复实现合并：

- JT808 首次定位与移动补报共享每通道成功处理；普通定位/转弯点复用广播发送器。失败通道继续重试，普通报告任一成功与告警全部在线通道成功的区别保持。
- 定位编码共享 28 字节基础体；避免生成随后覆盖的紧凑扩展、ACC 和告警字段。紧凑格式的物理 ACC、在线逻辑 ACC、历史定位标志语义保持。
- GGA/RMC 共用坐标、半球检查和符号转换。
- F39 主备服务器共用配置与查询实现；PID 去掉两次临时拷贝，保持验证和输出长度限制。
- DA218E 初始化改为有界寄存器表，保持原顺序及首错停止；诊断结构统一清零。

大部分无调用函数原本已被 LTO/链接器丢弃，删源码不等于释放同等 Flash；
实际收益主要来自重复执行路径和仍被初始化的废弃状态。

## 构建实测

命令：mingw32-make.exe -j4 size flash-guard BUILD=build-cleanup-20260921/after。
基线在同目录 baseline 下，前后编译配置 SHA256 一致。固定版本头，未运行刷新时间戳的 all。

| 项目 | 清理前 | 清理后 | 减少 |
| --- | ---: | ---: | ---: |
| App Flash 使用 | 106332 B | 105816 B | 516 B |
| App 剩余（上限 106496 B） | 164 B | 680 B | — |
| 静态 SRAM（不含链接预留栈） | 17288 B | 17268 B | 20 B |
| 已知 main 调用帧和 | 2624 B | 2592 B | 32 B |

Flash 硬容量通过，仍有 LOW_HEADROOM，680 B 不是充裕余量。
guard 自带旧基线存在 CONFIGURATION_CHANGED，不用于本轮节省量计算。

## 验证与限制

最终定向回归 25 个入口：24 个通过，1 个旧串口断言失败。
命令/退出码见 build-cleanup-20260921/final-tests.json，每项有单独日志。

通过项覆盖实际 JT808 主备发送/查询/休眠首点/转弯/盲区失败分支、弱信号过滤、
NMEA/GSV/保留时间、F39 配置/动作/端到端和车牌编码、震动灵敏度及初始化、
FOTA 检查点/授权掉电、AGNSS 存储、外部 Flash、功能开关及休眠源码契约。
源码契约检查不等于硬件验证。

- 定位编码：20000 组紧凑 + 40000 组在线/历史报文，与任务前编码逐字节一致。
- DA218E：核对全部 12 次写入（含 rearm），逐次注入失败，确认不继续写后续寄存器；前后均通过。
- 唤醒路由：128 种标志组合各重复 3 次，实际 C 路由前后均通过。
- 增强的 JT808 发送测试在任务前实现上也通过。
- ARM 构建、Flash 硬容量、release-guard、身份契约通过；收尾 git diff --check 通过。
  release_guard.py 只更新 jt808.h 审核指纹，已核实该头文件仅删除一行 getter 声明。
- 完整 RAM 门禁仍失败：68 个缺失帧、66 个间接转移、132 个尾转移、2 个内部调用、1 个循环。
  已知帧扣除后剩 4716 B，大于要求的 4096 B，但尚未证明完整栈/堆/异常边界。

以下旧测试问题在任务前完整 src/include 备份上复现，未为通过测试修改业务：

1. test_flash_config_v3.py：旧断言要求 anglerep_en == 1U。
2. test_motion_corner_policy.py：旧输入要求进入 MOTION_CORNER_TURN_ACTIVE。
3. test_at_config_serial_f39.py 和复用其夹具的 test_console_numeric.py：
   裸 SOSALM 命令被旧断言要求回复 OK。数值边界及主备端口检查已执行，失败出现在后续共用旧断言。
   本轮补齐夹具缺失的 FOTA/日志替身后显露此失败，前后同断言失败。

不声称全仓回归或完整发布门禁通过。弱信号静止漂移、真实低速起步、
震动唤醒、GNSS/DA218E 与休眠交互 **需要实机/HIL 验证**。

## 本轮文件与证据

生产源文件（src/）：agnss_storage.c、ec800m.c、f39_config_adapter.c、f39_reply.c、
flash_config.c、fota.c、fota_checkpoint.c、gps.c、hw_init.c、i2c_accel.c、jt808.c、power_mgr.c、spi_flash.c。

头文件（include/）：agnss_storage.h、ec800m.h、flash_config.h、fota.h、
fota_checkpoint.h、hw_init.h、i2c_accel.h、jt808.h、spi_flash.h。

测试（tools/tests/）：修改 test_at_config_serial_f39.py、test_f39_actions.py、
test_f39_end_to_end.py、test_gps_report_wire.py、test_i2c_accel_int1_rearm.py、
test_i2c_accel_vibration_adapter.py、test_stationary_location_owner.py；
新增 test_location_encoding_equivalence.py、test_power_wake_routing.py。
定位等价测试通过 --baseline 显式传入原始源码，原始备份保存在本轮证据目录。

其他：tools/release_guard.py、本报告、docs/superpowers/plans/2026-09-21-complete-code-cleanup.md。
build-cleanup-20260921/ 保存前后构建、原始备份、专项脚本、日志、
task.patch、source-inventory.json 和 final-evidence.json。
任务限定差异以这些备份为准，不将已有脏工作树与 Git HEAD 的差异归入本轮。
