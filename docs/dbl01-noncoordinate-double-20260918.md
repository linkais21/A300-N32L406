# DBL-01：非坐标 double 精度与尺寸试验

结论：本轮三个候选均未产生 Flash 收益，不合入默认固件。GNSS 非坐标字段与高程直接 float 化还会改变接收或报文结果。**本轮可兑现 Flash/RAM 节省均为 0 B，性能未测**；原审计中的 3,490 B 是共享双精度库占用，不是可以独立回收的空间。

## 精度契约与范围

| 使用点 | 当前契约 | 本轮处理 |
|---|---|---|
| gps 经纬度解析、STOP1 坐标；gps_report_filter、mileage、agnss_huada、JT808 坐标扩展 | 坐标保留 double，包含坐标相减与量化前运算 | 保留 |
| gps GGA 的 HDOP、高程、椭球差 | 十进制严格解析、拒绝非法/溢出字段，再由 double 转为 float 存储 | 试验独立 float 解析器，保留整数词法检查 |
| gps RMC 的节速度、航向 | 航向在 double 域判断 `[0,360)`；速度先乘 double 1.852 再转 float | 与 GGA 合成 gps_float 候选，记录接收、值和派生速度字段差异 |
| JT808 altitude_extension_tail | `floor(abs(binary32高度)*1000) % 1000`；非有限或缩放后 >=2^32 返回 0 | 比较直接 float 乘法与精确整数拆解 |
| debug_uart %f | C 可变参数 float 提升为 double，格式舍入与坐标日志也依赖 double | 保留；不能改为 `va_arg(ap,float)`，也不能仅为删库关闭日志 |
| ADC 电压、速度策略、转角策略 | 已使用 float | 不重复降精度 |

整数候选针对 IEEE binary32：规格化数乘 1000 等价于 `significand * 125 * 2^(exponent-147)`，24 位有效数乘 125 可放入 uint32_t；移位前检查边界，右移保持正数向下取整。零、非规格化数均不足 1 mm，NaN/Inf 和溢出返回 0。double 基线的该乘法也能精确容纳有效位，因此该候选旨在保持原始取整，而非引入容差。它仅留在试验工具中，未增加生产平台的浮点表示依赖。

## ARM 全量构建

同一源码、同一构建身份、ARM GCC 14.3.1、当前 Makefile 默认配置，隔离 BUILD 和单文件 overlay。最终证据：`build/dbl01-final-20260918/`，包含命令、退出码、输入 SHA-256、ELF/MAP/BIN、段与符号表。

| 配置 | BIN B | 相比基线增加 B | 剩余 Flash B | 静态 RAM B |
|---|---:|---:|---:|---:|
| 基线 | 106160 | 0 | 336 | 17756 |
| 高程 float | 106176 | 16 | 320 | 17756 |
| 高程精确整数 | 106192 | 32 | 304 | 17756 |
| GNSS 非坐标 float | 106256 | 96 | 240 | 17756 |

静态 RAM 为 `.data 304 + .bss 17452`，不含堆/栈预留。当前工作树与旧审计输入不同，不直接与旧报告 106176 B 比较收益。只使用本表同输入 A/B 差额；LTO 全程序布局、共享解析器与双精度库的保留决定最终尺寸，不能由局部指令减少推算净收益。

四组构建成功、无 warning，release-guard、平台信任锚、Flash 容量检查通过。四组 release-gate 都退出 2：**ram-guard 因整程序栈/堆/异常证据不完整失败**；stack-guard 同样报告 INCOMPLETE。基线已存在该失败，不宣称发布门禁通过，也不把试验镜像作为交付包。

## 真实 C 回放

高程测试从实际 `src/jt808.c` 抽取函数，比较两种 overlay。覆盖所有指数/符号、尾数边缘、固定种子随机 binary32、0..1000 m 每个毫米边界的 float 邻点，共 **5,048,578** 个样本：

- 精确整数候选：0 个结果差异。
- 直接 float 候选：569,451 个差异，作为负对照确认测试能发现精度回归。
- 示例：float 高度 `32.0009995`，double 基线毫米尾数为 0，float 候选为 1。没有以“误差小”放宽断言。

这不是遍历全部 2^32 个输入；也未测 ARM 周期或对 signaling NaN 的异常标志。测试初次执行因候选工具尚未实现而缺模块，这只是脚手架 RED；数值回归识别能力由上述 float 负对照证明。

GNSS 从实际 `src/gps.c` 抽取完整 GGA/RMC 解析函数，经相同合成字段重放 **17,690** 条：

| 指标 | 差异数 |
|---|---:|
| 接收/格式判定 | 1 |
| 两者均接收时，非坐标字段值 | 769 |
| 两者均接收时，派生 0.1 km/h 速度字段 | 11 |
| `<2 km/h` 判定 | 0 |
| `>60 km/h` 判定 | 0 |

共同接收的坐标逐项一致。边界例：航向 `359.999999999` 在基线 double 校验时合法，float 提前舍入成 360 后拒绝整条 RMC。另一个样本节速度 `1589.956809646` 导致速度字段由 29446 变为 29445。高速度值是解析器接受域测试，不代表真实行车速度。

原始输出和全部差异保存在 `build/dbl01-replay-20260918/`，结果显式为 `behavior_equivalent=false`、`release_approved=false`。数字实验在解析函数入口注入字段，不覆盖 UART、checksum、队列、跨句状态或完整 JT808 编码器；速度字段/阈值是观察探针，不宣称端到端状态机等价。既有 NMEA 与 JT808 参数报文回归另行执行通过。

## 复现与工作树保护

新增文件仅本文、`tools/experiments/noncoordinate_double_trial.py`、`tools/experiments/replay_noncoordinate_double.py` 和 `tools/tests/test_noncoordinate_double_trial.py`；审计优先级行同步链接本结论。输出目录必须是 build 下尚不存在的子目录。

```powershell
python tools/tests/test_noncoordinate_double_trial.py
python tools/experiments/replay_noncoordinate_double.py --output build/dbl01-replay-new
python tools/experiments/noncoordinate_double_trial.py --output build/dbl01-size-new
python tools/tests/test_nmea_replay.py
python tools/tests/test_jt808_params_wire.py
```

三项测试的命令/退出码与输出在 `build/dbl01-validation-20260918/`。首轮 `build/dbl01-20260918/` 被输入哈希检查拒绝：现有 `make all` 自动刷新 `include/build_version.h`、`include/config.h`、`release_identity.json` 时间戳。工具已用 `make -o include/build_version.h` 固定身份；这三个文件均恢复到首轮试验前 SHA-256 完全一致的字节，之后最终构建再次验证输入未变。未覆盖原 build 默认固件或已有交付包。

后续若以运行时性能为目标，需要实机/HIL 验证，包括 ARM 数值回放、周期/最坏延迟、真实 GNSS 轨迹及栈水位。当前没有用新增 Flash 换取性能的实测依据；不采用这三个候选，也不关闭 DBL-01 的全部潜在优化空间。
