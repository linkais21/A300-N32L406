# 保持业务逻辑的 Flash 优化

## 结果

以包含弱信号静止优化的当前 V3.070 工作树重新构建基线，净省 **368 字节**。

| 指标 | 基线 | 最终 |
|---|---:|---:|
| App Flash 加载跨度 / BIN | 105548 B | 105180 B |
| 106496 B App 分区余量 | 948 B | 1316 B |
| 静态 RAM（不含链接器堆栈预留） | 17264 B | 17264 B |
| 已知 main 调用链帧和 | 2624 B | 2624 B |

仍有 LOW_HEADROOM 告警，不能把 1316 B 视为充足扩展空间。
未修改 Makefile、优化级别、功能开关、版本身份、Flash 分区或发布门禁。
构建使用 `size flash-guard`，固定版本时间，不执行会刷新版本的 `all`。

## 实际修改

- `src/jt808.c`：坐标尾数和电压转换各保留一个函数体，避免两组调用被重复展开；
  日期有效性验证复用现有月份天数函数。数值精度、舍入/截断、饱和、时区和闰年规则不变。
- `src/gps_report_filter.c`：`isfinite(x) && x >= -limit && x <= limit`
  改为 `fabs(x) <= limit`，仍拒绝 NaN、正负无穷和越界坐标。
- `src/gps.c`、`src/mileage.c`：同样缩短对称坐标范围判断。
  原先拒绝式 `x < -limit || x > limit` 对 NaN 的行为保持为 false；
  接受式判断对 NaN 仍为 false。没有借体积优化改变原有无序比较语义。
- 新增 `tools/tests/test_location_numeric_equivalence.py` 和本文。

弱信号保护阈值、锁点状态机、传感器采样、未定位上报、日志、超时、重试、
鉴权、安全控制及掉电恢复均未删改。主机等价检查不等于目标硬件时序验证。

## 测量与审核

所有试验先在独立源码覆盖目录构建，有收益后才写入上述四个生产文件。

| 累计候选 | Flash | 相对基线节省 |
|---|---:|---:|
| 坐标/电压转换不重复展开 | 105436 B | 112 B |
| 加上静止过滤器坐标判断 | 105292 B | 256 B |
| 加上保留定位与里程坐标判断 | 105228 B | 320 B |
| 加上月份天数复用 | 105180 B | 368 B |

审核保留日期调用前的月份合法性检查；所有范围变换仅用于纯数值字段，
不改变原始数据、外部调用或结构布局。三个 noinline 仅影响代码生成和调用边界。
没有采用数值降精度、日志删除、校验删除、状态机裁剪或全局激进编译参数。

## 验证

ARM GNU 14.3，命令：

```text
mingw32-make.exe -j4 size flash-guard BUILD=build-flash-audit-20260920/baseline
mingw32-make.exe -j4 size flash-guard BUILD=build-flash-audit-20260920/final
python build-flash-audit-20260920/verify.py
mingw32-make.exe release-guard ram-guard BUILD=build-flash-audit-20260920/final
```

前两项构建和 Flash guard 通过。验证脚本的 **11 项检查通过**：

- `test_location_numeric_equivalence.py`：编译生产范围/日期函数，比较原语义；
  包含坐标端点及相邻值、NaN/Inf/有符号零/次正规数、30 万组 IEEE 输入，
  遍历 uint16 年份中 2000–65535 的所有月份及合法/非法日期边界。
- `test_gps_report_filter.py`、`test_gps_report_wire.py`
- `test_gps_retained_clock.py`、`test_gps_ntp_apply.py`
- `test_mileage_quantization.py`、`test_mileage_persistence.py`
- `test_stationary_math.py`、`test_feature_guards.py`
- `test_stationary_location_owner.py`、`test_ram01_frame_budget.py`

新增等价测试也在变更前通过；这是等价重构，不伪造功能缺陷 RED。
release-guard 通过；完整命令因 **ram-guard 失败返回 2**：全程序栈证据不完整，
missing frames=68、indirect=66、tail=132、internal calls=2、cycles=1。
必要帧预算测试通过不代表 RAM 门禁通过。

范围内差异/空白检查通过。`build-flash-audit-20260920/inputs.json` 绑定起始工作树，
`final-inputs.json` 绑定最终输入；核对仅上述四个生产源文件变化，其余记录输入不变。
本轮精确差异见 `changes.patch`，每项测试命令/退出码见 `tests.json`，
构建和门禁日志分别为 `baseline.log`、`final.log`、`guards.log`。

**需要实机/HIL 验证**：弱信号静止与起步、GNSS 丢失恢复、0200 主备报文和跨日时区，
以及目标设备栈水位/运行时序。没有烧录、发布、提交或覆盖既有交付产物。
