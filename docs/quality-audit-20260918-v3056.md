# A300 固件：企业级代码质量与资源优化专项诊断（V3.056）

> 09-18 后续实测更新：本文原始摘要中 `-finline-limit=32` 的历史 −200 B 预期已被[同输入对照评估](inline-limit32-evaluation-20260918.md)取代：当前增加 240 B、静态 RAM 无收益，不采用。原始审计基线保留作历史记录，P3 表格已更新。

日期：2026-09-18。范围：`A300-first` App 当前工作树（HEAD `6eab8e6` + 未提交修改，`release_identity.json` = V3.056）。**只分析，未修改任何源码、Makefile、链接脚本或版本文件。** 本轮唯一新增文件为本报告及 `nm_all.txt`、`str_all.txt` 两个符号/字符串导出（在 A300-first 根目录，可随时删除）。

本报告是 2026-09-12 审计（`build/quality-audit-20260912/REPORT.md`）的增量复审：先核对该轮 14 项发现的整改状态，再报告新基线与新发现。上一轮已有的方法学结论（缓冲语义边界表、不推荐项清单）仍然有效，不在此重复全文。

## 一页摘要

| 项目 | 结论 |
|---|---|
| 基线 | N32L406CBL7，Cortex-M4 @64 MHz，App 分区 106,496 B @0x08006000，SRAM 24,576 B；ARM GCC 14.3.1，-Os + LTO(partition=one) + -ffunction/data-sections + --gc-sections + nano.specs，-g0，全量构建成功、无警告 |
| App Flash | **106,176 / 106,496 B = 99.70%，仅剩 320 B**。flash-guard 已现场告警 LOW_HEADROOM。比 09-12 审计（105,776 B，剩 720 B）又增 400 B；比 09-16 试验基线（104,560 B，剩 1,936 B）两天内净增 1,616 B |
| 静态 RAM | .data 304 + .bss 17,764 = **18,068 B（73.5%）**，加堆 1,024 + 栈预留 2,048 = 21,140 B（86.02%）。比 09-12 增 248 B |
| RAM 安全间隙 | map_ram_guard 实测：静态 18,068 + 已证调用链 2,408 → 剩 4,100 B，对比要求间隙 4,096 B，**裕量仅 4 B**；且栈证据不完整（76 缺失帧/52 间接跳转），`mingw32-make ram-guard` 当前判 **FAIL** |
| 三大 Flash 来源 | ① 业务状态机群（jt808 ~7.2K、fota ~6.9K、blind_zone ~6.2K、ec800m ~6.2K）；② .rodata 字符串 ~10.3K（绝大部分为日志格式串）；③ 软件双精度算术 3,490 B（libgcc __aeabi_d*） |
| 三大 RAM 对象 | s_workspace 4,096（AGNSS 流）；s_rx 1,040（JT808 双通道 RX）；s_tx_workspace 1,029（JT808 TX）——均有语义边界（见 09-12 报告 §4 生命周期表，本轮抽查尺寸仍一致） |
| 三大疑似性能热点 | ① SPI flash 擦除期间 ready() 忙等（4 KiB 扇区典型 45–400 ms）停摆主循环；② 同步日志/串口线速等待（09-12 PERF-03 仍开放）；③ 大状态机每轮全量推进的空转成本（未测） |
| 三大质量问题 | ① 发布门禁 ram-guard 在 HEAD 判 FAIL 但 V3.056 交付包已产出（门禁与发布入口不一致）；② Release 固件保留全量日志字符串且无日志分级开关；③ 三套命令面（AT/SMS/F39）合计约 9.4 KB，解析/应用/回复逻辑部分重叠 |
| 可安全承诺节省 | **无试验构建佐证前：Flash 0 B、RAM 0 B。** 有实测依据的候选：exit→stdio 链移除（估 1–1.5 KB Flash + 312 B RAM，需一次试验构建验证）；保守日志裁剪 200 B（09-16 已实测）；-finline-limit=32（历史实测 200 B） |
| 溢出风险 | 本次链接无越界；但 Flash 余量 320 B、RAM 间隙裕量 4 B，**任何新增功能都会触顶**。无实机栈溢出证据，但也无完整反证（栈证据不完整） |

## 与 09-12 审计的差异（整改核实）

| 09-12 发现 | 当前状态 | 本轮证据 |
|---|---|---|
| DUP-01 OTA 忙谓词重复 | ✅ 已整改（`fota_is_active`） | docs/dup01-shared-ota-query-20260915.md |
| DUP-02 双 SHA 实现 | ✅ 已整改（共用 src/sha256.c） | docs/dup02-shared-sha-status-20260915.md；nm 中 sha256 仅 578 B 一份 |
| PERF-01 里程双精度重复计算 | ✅ 大幅整改：受限 double 多项式已采纳进 src/mileage.c（19 阶正弦多项式 + 8192 m 钳制），**libm 从 8,252 B 降到 980 B**，sin/cos/atan2/rem_pio2 已从 ELF 消失，main 从 8,572 B 降到 2,344 B | src/mileage.c:43,77；map 中 libm 合计 980 B；nm 无 atan/rem_pio2 |
| PERF-02 AGNSS 重复整包校验 | ✅ 已整改 | docs/perf02-agnss-snapshot.md |
| PERF-04 OTA 单次扫描 | ✅ 已整改 | docs/perf04-ota-single-scan-20260915.md |
| PERF-05 中科微 O(n²) | ✅ 以退役中科微整体解决 | docs/perf05-retire-zhongkewei-20260915.md；Makefile C_SRCS 无该文件 |
| BUILD-01 增量构建缺头依赖 | ✅ 已整改（-MMD/-MP + 构建参数指纹 BUILD_CONFIG_HASH） | Makefile:182–204 |
| RAM-04 s_rx 8 B 填充 | ✅ 已整改（1,048 → 1,040 B） | nm：s_rx 0x410 |
| RAM-01 栈 gate 低估 | ⚠️ 部分整改：新增 stack_usage_guard record/check、stack-report 目标；但证据仍不完整（76 缺失帧），ram-guard 判 FAIL——见本轮 GATE-01 | 本轮 ram-guard 输出 |
| RAM-02 堆边界 | ❌ 仍开放（_sbrk 仍只比较 _estack；__sf 312 B 仍在） | nm：__sf 0x138 |
| RES-01 Flash 余量 | ❌ 恶化：720 → 320 B | flash-guard 输出 |
| PERF-03 同步日志线速等待 | ❌ 仍开放 | src/debug_uart.c 逐字节轮询未变 |
| BUILD-02 多构建入口 | ❌ 仍开放（build_all.ps1 未退役） | 文件仍在 |
| CONC-01 命令槽交接 | ❌ 仍开放 | src/main.c s_cmd_buf 结构未变 |

09-12 至今 Flash 净演化：受限 double 数学落地约省 6.8 KB，但华大 AGNSS 集成、产线修复 3–6、0x8103 参数、日志字段/静态漂移移植（docs/production-fix*.md、huada-*.md、log-version-stationary-20260917.md）等新功能把它重新消耗，还倒欠 400 B。**两天消耗 1.6 KB 的斜率是比任何单项优化更重要的管理信号。**

## 本轮基线（全部实测）

### 构建配置核对（用户检查单 §六）

- 优化：`-Os -finline-limit=64`；main/fota/签名/uECC 附加 `-fno-inline-functions-called-once`（Makefile:128,246）
- LTO：`-flto=1 -flto-partition=one`；签名边界（firmware_signature.c、uECC.c）刻意 `-fno-lto`（Makefile:148,213–222）
- section GC：`-ffunction-sections -fdata-sections` + `-Wl,--gc-sections` ✅
- 运行库：`--specs=nano.specs` ✅；未链接 `_printf_float`（nm 计数 0）✅；未链接 64 位除法辅助（无 __aeabi_uldivmod/ldivmod）✅
- 调试信息：`-g0` 默认 ✅（ELF 残留 .debug_frame 2,880 B 来自预编译库，不进 BIN）
- MAP：`-Wl,-Map` + `--print-memory-usage` ✅；栈分析 `-fstack-usage` ✅
- 警告：`-Wall -Wextra`，SDK 单独压制 2 项；本轮全量构建 0 警告 ✅
- C99 无异常/RTTI 议题；无 -ffast-math ✅
- 结论：**编译/链接配置已处于该工具链的合理最优位形**，剩余旋钮仅 -finline-limit=32（历史实测省 200 B，未实机验证）

### 产物

| 项目 | 数值 |
|---|---:|
| BIN（Flash 载荷跨度） | 106,176 B |
| HEX（文本编码体积） | 298,698 B |
| ELF 文件 | 164,380 B |
| .isr_vector / .text / .rodata | 328 / 92,560 / 12,960 B |
| .data / .bss | 304 / 17,764 B |
| GNU size | text=105,856 data=312 bss=20,836 |
| 堆 / 主栈预留 | 1,024 / 2,048 B（ldscript/n32l406.ld:18–19），MSP=0x20006000，无独立中断栈 |

### 最大函数（nm 去别名，前 15）

| 符号 | B | 模块 |
|---|---:|---|
| blind_zone_recovery_process.part.0 | 4,040 | blind_zone.c |
| ec800m_process | 3,612 | ec800m.c |
| process_frame | 2,770 | jt808.c |
| at_config_process | 2,412 | at_config.c |
| main | 2,344 | main.c |
| dispatch_nmea | 1,812 | gps.c |
| fota_process | 1,720 | fota.c |
| jt808_process | 1,484 | jt808.c |
| cfg_init | 1,404 | flash_config.c |
| prepare_operation | 1,344 | f39_config_adapter.c |
| work_mode_process | 1,308 | work_mode.c |
| f39_execute.constprop.0 | 1,256 | f39_reply.c |
| process_location_timer | 1,156 | jt808.c |
| i2c_accel_init | 1,036 | i2c_accel.c |
| blind_zone_replay_process | 1,032 | blind_zone_replay.c |

### 最大 RAM 对象（前 20，nm）

s_workspace 4,096；s_rx 1,040；s_tx_workspace 1,029；s_service_workspace 1,024；s_deferred_urc 1,024；EC800M_RX_BUF 1,024；s_cfg(flash_config) 788；s_records 528；s_at_resp 512；s_body 500；s_queue 428；g_work_mode 324（较 09-12 的 388 已缩）；__sf 312（libc）；s_tcp 304；s_path/s_sms_text/s_retry_reply/s_nmea_slots/s_line_buf 各 256；s_cfg(jt808) 202。缓冲区语义边界与缩减判断沿用 09-12 报告 §4 表（本轮抽查尺寸一致或更小），**无实机高水位数据前可安全缩减 = 0 B**。

### Flash 模块归组（符号前缀近似，含 rodata）

jt808* 7.2K｜fota* 6.9K｜blind_zone* 6.2K｜ec800m 6.2K｜gps* 4.0K｜cfg_query 3.3K｜f39* 3.0K + process_frame 2.8K｜at_config 2.9K｜SDK 外设库 2.8K｜**libgcc 双精度模拟 3,490 B**（__aeabi_dadd 630/dsub 634/dmul 596/ddiv 464/比较与转换 ~1.2K，按地址去重）｜work_mode* 2.7K｜main 2.3K｜agnss* 2.3K｜micro-ecc 2,086 B｜i2c_accel 2.0K｜mileage 1.5K｜libm 980 B（仅 sqrtf/fmodf 族）｜libc-printf ~1.7K（_printf_i 588、_svfprintf_r×2 992、snprintf 族）。

### 字符串（.rodata ~12.9K 中约 10.3K 为字符串常量）

按日志标签归因（strings 扫描，含少量误码）：[FOTA] 1,173 B、[4G-RX] 584、[ACCEL] 546、[808] 535、[4G] 423、[CFG] 371、其余标签各 <300 B；未标签部分（GNSSDIAG/FACTORYCAP/JSON/URL/AT 命令等）占大头。**`dbg_printf` 无任何编译期日志分级开关**（include/debug_uart.h:9），全部 214 处调用点的格式串进入 Release 固件。09-16 试验实测：仅裁 4 条白名单高频日志 = 200 B；字符串不可全删（含协议/AT/URL 功能串）。

## 问题清单

严重度定义同 09-12 报告。已在上表标 ✅ 的整改项不再单列。

### RES-01′ · P1 · Flash · 余量 320 B，消耗斜率不可持续

- **定位：** ldscript/n32l406.ld:23；build/flash-capacity.json；flash-guard 现场输出 `used=106176/106496 remaining=320`，ALERT LOW_HEADROOM。
- **原因：** 编译位形已最优、既往大额优化（双精度数学 −6.8K）已落地并被功能增量（华大 AGNSS、产线修复、0x8103、日志字段移植）反超。
- **影响：** 下一个百字节级功能即链接失败或迫使仓促裁剪；OTA 镜像上限 106,496 B 是发布契约，不可挪 Bootloader 分区。
- **建议：** ① 把 flash-guard 余量写入每轮交付验收（当前只告警不拦截首次基线）；② 排队执行本报告 LIBC-01 / STR-01 试验构建，把余量恢复到 ≥2 KB 后再接新功能；③ 每个新功能报价 Flash 预算。
- **预计变化：** 本项自身 0 B；管理措施。风险低。**验证：** flash-capacity.json 逐版本对比。**置信度：** 高（实测）。

### GATE-01 · P1 · 编译配置/流程 · ram-guard 在 HEAD 判 FAIL，与已产出的 V3.056 交付包矛盾

- **定位：** Makefile:263–264；tools/map_ram_guard.py；tools/stack_usage_guard.py；本轮输出 `RAM guard failed: incomplete stack evidence`（missing frames=76, indirect=52, tail=142, cycles=1）；`RAM diagnostic: static=18068 known_call_frames=2408 remaining=4100 required_gap=4096`。
- **原因：** 09-12 RAM-01 的整改把栈证据要求收严到"无完整证据即 FAIL"，但间接调用/库帧/尾调用尚未补全建模；而 `release_identity.json` 显示 V3.056 交付包昨日已产出——发布入口（tools/build_dev_release.py）未把这个 FAIL 作为阻断，即 09-12 BUILD-02"门禁与发布入口分裂"仍在发生。
- **影响：** "release-gate 通过"字样失去可信度；RAM 间隙裕量实测只有 4 B，恰恰是最需要这个门禁说话的时刻。
- **建议：** 二选一并写入流程：(a) 补全 76 个缺失帧/间接调用注记使 gate 可判 PASS；(b) 让 build_dev_release.py 显式执行完整 release-gate 并在 FAIL 时拒绝出包。不要静默降低 required_gap。
- **预计变化：** Flash/RAM/性能 0；纯流程。风险低。**验证：** `mingw32-make release-gate` 全绿后再出下一版。**置信度：** 高（现场复现）。

### RAM-05 · P1 · RAM · 静态 RAM 对要求间隙的裕量只剩 4 B

- **定位：** map_ram_guard 输出（上项）；对比 09-12：静态 17,820 → 18,068（+248 B，主要来自华大集成与新诊断字段）。
- **影响：** 再增加任何 ≥4 B 的静态对象，guard 的 4,096 B 间隙要求即被击穿；而真实运行栈峰值（HEALTH 日志 STK_PEAK/HEAP_USED/RAM_GAP 字段已具备采集能力）尚未见本轮版本的实测记录。
- **建议：** ① 新功能与新缓冲一律先给 RAM 报价；② 用现有 HEALTH 日志在 V3.056 实机上采集冷启动/OTA 验签/双通道并发/AGNSS 注入的 STK_PEAK 与 HEAP_USED——若 HEAP_USED 恒为 0（应用层无 malloc，本轮已核实 src/ 无一处 malloc/calloc/realloc），堆预留 1,024 B 可评估减半，直接买回 512 B 间隙；此评估必须以实测为前提（09-12 RAM-02 所述库分配路径仍存在）。
- **预计变化：** 候选 RAM +512 B 间隙（待实测批准）。风险：中（库 ENOMEM 行为需回归）。**验证：** 实机 HEALTH 水位 + host 分配失败注入。**置信度：** 高（静态部分实测）；堆候选待测。

### LIBC-01 · P2 · Flash+RAM · 从不调用的 exit() 拖入整套 stdio 清理链

- **定位：** MAP 归档链：`crt0.o(exit) → libc_a-exit.o(__stdio_exit_handler) → libc_a-findfp.o → stdio.o/fwalk.o/lock.o/closer.o/readr.o/writer.o/lseekr.o/reent 链 + _malloc_r`；RAM 侧 `__sf` 312 B（nm 0x138）+ 锁对象；src/syscalls.c 未提供自有 exit。
- **原因：** 裸机主循环永不返回、永不调用 exit，但 crt0 无条件引用 exit，newlib 的 exit 又注册 stdio 清理，把 FILE 机制整体拖进镜像。应用格式化仅用 snprintf/vsnprintf（nano 版在栈上建局部 FILE，不需要 __sf）。
- **影响：** 估 1–1.5 KB Flash + 312 B 以上 RAM 被从不执行的代码占用（估算依据：上述成员在 MAP 中的段和；准确值需试验构建）。
- **建议：** 试验构建验证：在 syscalls.c 提供自有 `void exit(int) __attribute__((noreturn))`（复位或死循环+喂狗语义需项目决定），对比 BIN/MAP 确认 findfp 链消失、snprintf 行为不变；host tests + 实机冒烟。这是当前唯一"不改任何业务行为、收益过千字节"的候选。
- **预计变化：** Flash −1~−1.5 KB（待测）；RAM −312 B 以上（待测）；性能 0；中断 0。风险：低-中（需确认无隐式 stdio 依赖；异常路径语义要评审）。**验证：** 试验构建 BIN 对比 + nm 无 __sf + 全量 host tests + HIL 冒烟。**置信度：** 链路证据高；数值待试验构建。

### STR-01 · P2 · Flash · Release 固件含 ~10 KB 日志/格式字符串，且无日志分级机制

- **定位：** include/debug_uart.h:9（dbg_printf 无级别参数、无编译开关）；src/ 214 处调用（ec800m 35、at_config 35、fota 30、jt808 28、main 27…）；.rodata 字符串 ~10.3 KB。
- **原因：** 日志体系一直按"运营诊断必需"整体保留；09-16 试验证明白名单式裁剪安全可控但只做了 4 条（200 B）。
- **影响：** 字符串是第 2 大 Flash 来源；但它同时是现场排障的核心资产（PERF-01/QIRD 等问题都靠它定位），一刀切裁剪违反项目约束。
- **建议：** 引入编译期日志分级（如 `LOG_LEVEL_RELEASE` 把 VERBOSE 级调用编译成空静态函数，保留参数求值副作用——09-16 试验已验证该模式可被 LTO 完全消除），按上文标签字节表逐标签定预算；哪些标签属 VERBOSE 需运营/HIL 相关方确认，**不属于本轮可单方面决定的优化**。
- **预计变化：** Flash −1~−4 KB（取决于分级授权范围；仅 4 条白名单=−200 B 已实测）；RAM 0；性能略正（少量格式化消失）。风险：中（可观察性变化，HIL 工具链依赖需同步）。**验证：** 试验构建 + 日志消费方（HIL 清单/串口分析工具）会签。**置信度：** 机制高；数值取决于授权范围。

### DBL-01 · P2 · Flash/性能 · 残余软件双精度算术 3,490 B

- **定位：** nm 去重合计 3,490 B（__aeabi_dadd/dsub/dmul/ddiv/比较/转换族）；使用方：src/mileage.c（坐标存储与多项式内部）、src/gps.c、src/gps_report_filter.c、src/jt808.c、src/debug_uart.c（%f 支持）、src/agnss_huada.c。
- **原因：** FPU 仅单精度；坐标 1e-7 度精度需要 9 位有效数字，float（7 位）不达标，故坐标链保留 double 是**正确的**；但并非全部 6 个文件的每处 double 都承载坐标精度。
- **影响：** 每次 double 乘除 ~100-300 周期（软件模拟）；Flash 3.5 KB。里程热路径已被 09-16 的受限多项式方案控制，剩余调用频率未测。
- **建议：** 逐调用点建立精度契约（哪些是坐标、哪些是电压/速度/统计量），非坐标路径评估 float 化；必须复制 09-16 里程试验的方法论（真实 C 回放 + 决策差异清单），不接受"数值差异极小所以无影响"的论证。dbg_printf 的 %f 支持（648 B 函数自带 double 转换）与日志分级联动评估。
- **预计变化：** Flash 上限 −3.5 KB（实际远低于上限，因坐标链必须保留）；性能待测。风险：中高（精度/边界语义）。**验证：** 回放对比 + host tests + 实机轨迹一致性。**置信度：** 占用数值高；可省比例待逐点分析。

### PERF-06 · P2 · 性能 · SPI flash 擦除期间主循环完全停摆（本轮已核实代码路径）

- **定位：** src/spi_flash.c:97–110 `ready()`：忙等轮询 SR1（TICK_MS 超时 + guard 计数），无让出、无喂狗调用；src/spi_flash.c:172 扇区擦除后即进入该等待。BY25Q16 4 KiB 扇区擦除典型 45 ms、最坏 ~400 ms。src/hw_init.c:396–400：IWDG = LSI/256、reload 4095 ≈ **26 s**——看门狗无复位风险。
- **影响：** 擦除窗口内 GPS NMEA 双槽（2×128 B，ISR 收句）可能溢出（现有 QUEUE_DROP/OREF 计数器可直接观测）；EC800M 侧数据由模组内部缓存（QIRD 拉取模型），风险有界。属"疑似性能热点"：擦除只发生在盲区滚动/OTA/配置提交等阶段，不是恒定成本。
- **建议：** 先测不改：在盲区高负载与 OTA 下载阶段读取 GNSSDIAG 的 QUEUE_DROP 增量。若确有丢句，再评估把 ready() 改为主循环状态机步进（ext_flash_store 的 owner 模型天然支持挂起-恢复），不改 NOR 事务语义。
- **预计变化：** 测量阶段 0；改造阶段 Flash 略增（状态机）、RAM +数字节、GPS 丢句率下降。风险：中（Flash 事务时序）。**验证：** 实机计数器 A/B + 掉电切点回归。**置信度：** 代码路径高；实际丢句待测。

### DUP-03 · P3 · 重复代码 · 剩余重复均为"维护型"，无 Flash 收益

- **定位/证据：** 09-12 审计已证明 GPIO AF 助手、OTA 谓词、SHA 表、月份表等在 LTO 下同址合并（二进制零成本）；DUP-01/02 源码级整改后，本轮 nm 抽查未发现新的同址别名群。三套命令面 at_config(2.9K)+f39(3.0K+2.8K frame)+sms(0.7K) 合计 ~9.4 KB，语义重叠但报文格式/鉴权/回复通道不同，f39_config_adapter 已统一配置应用层。
- **建议：** 命令面收敛只作为长期架构方向（新命令只进 adapter，旧面冻结），不作为 Flash 抢救手段——重构风险与三通道回归成本远超收益。本轮子代理深度扫描因账户额度中断，逐函数相似度矩阵未完成；如需穷尽式重复扫描，待额度恢复后可补跑。
- **置信度：** 中（覆盖不完整，已明示）。

### 沿用未关闭项（不重复展开）

- **PERF-03（同步日志线速等待）**、**CONC-01（命令槽交接协议）**、**BUILD-02（build_all.ps1 未退役）**、**RAM-02（_sbrk 无硬边界）**、**DOC-01（注释/单位漂移）**：09-12 报告的定位、建议、验证方法全部仍然适用，状态=开放。

## 优化优先级表

| 优先级 | 优化项 | Flash收益 | RAM收益 | 性能收益 | 修改风险 | 建议 |
|---|---|---|---|---|---|---|
| P1 | GATE-01：ram-guard 判定与发布入口一致化 | 0 | 度量可信 | 0 | 低 | 立即；先于一切"省字节" |
| P1 | RES-01′：Flash 预算管理 + 余量恢复排期 | 管理项 | 0 | 0 | 低 | 立即 |
| P1 | RAM-05：实机 STK_PEAK/HEAP_USED 采集 | 0 | 决定堆候选 | 0 | 低 | 立即（日志字段已具备） |
| P2 | LIBC-01：自有 exit() 消除 stdio 链 | **−1~1.5 KB（待测）** | **−312 B+（待测）** | 0 | 低-中 | 第一个试验构建；收益/风险比最好 |
| P2 | STR-01：编译期日志分级 | −1~4 KB（视授权） | 0 | 略正 | 中（可观察性） | 需运营/HIL 会签后实施 |
| P2 | RAM-05 堆候选：1024→512 | 0 | +512 B 间隙 | 0 | 中 | 仅在 HEAP_USED 实测=0 后 |
| P2 | PERF-06：擦除窗口 GPS 丢句测量 | 0 | 0 | 数据决定 | 低（纯测量） | 用现有计数器，先测后改 |
| P2 | DBL-01：非坐标 double 精度契约评估 | 本轮 0；三候选增加 16/32/96 B | 0 | 未测 | 中高 | [真实 C 回放与 ARM 试验](dbl01-noncoordinate-double-20260918.md)：三候选均不采用 |
| P3 | -finline-limit=32 | 当前同输入实测 **+240 B**（增大） | 0 | 未测 | 中 | **不采用，保留 64**；[09-18 对照评估](inline-limit32-evaluation-20260918.md)取代历史 −200 B 预期 |
| P3 | 命令面长期收敛 | ~0 | 0 | 0 | 高 | 只约束增量，不重构存量 |
| 不推荐 | 缩通信缓冲/关校验或日志一刀切/改 App-Boot 分界/-O2/-O3/-ffast-math/缩 NMEA 槽 | — | — | — | 高 | 同 09-12 结论，维持排除 |

## 验证记录与局限

1. 全量构建成功（cmd + 无 sh 的干净 PATH；Git Bash 直接调用会因 make 拾取 sh.exe 失败），0 警告；size/nm/map/strings/flash-guard 输出均为本轮实测。`stack-report`/`ram-guard`/`stack-guard` 已执行：ram-guard FAIL（GATE-01），libc_parser_guard PASS。
2. 未执行 release-guard/platform-trust-guard/flash（后两者一为已跑过的等价测试、一需硬件授权）；未运行 host tests 全集（本轮无代码修改，无回归对象）。
3. 计划中的 5 个并行深度扫描子代理（重复代码/死代码/RAM/性能/质量）因 API 账户额度不足全部中断；其部分线索（SPI flash 阻塞、zhongkewei 退役确认）已由主会话逐条人工核实并纳入本报告。**重复代码与死代码的穷尽式扫描覆盖不完整**，已在 DUP-03 标明。
4. 所有性能项无 CPU 周期/IRQ 延迟实测，一律标"疑似热点/待测"；所有节省数值除引用 09-16 实测外均标"待试验构建"。
5. 本轮未修改任何跟踪文件；新增文件仅本报告与 nm_all.txt/str_all.txt 导出。未提交、未推送、未烧录、未部署。
