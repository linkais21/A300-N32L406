# 弱信号静止漂移优化

## 输入与范围

用户确认 V3.070（20260920214405）在完全静止、无振动时出现 1–3 km/h 和坐标变化。
没有该时间段串口日志，不能确认现场 HDOP、滤波状态或解锁原因。
本次修复已锁点状态下的弱质量小速度误解锁，以及短暂失去定位后锚点丢失；
不声称已完整复现现场。截图的“定位信号强”不等同于 HDOP 精度指标。

## 行为

- 已锁点、加速度窗口 <=120 mg、速度 <=3 km/h，且卫星数 <6 或
  HDOP 非有限数/<=0/>2.5 时，不把该速度计为运动证据。
- 正常质量下仍连续 3 个 >=2 km/h 的新 RMC 解锁；弱质量速度 >3 km/h
  也按 3 个新 RMC 解锁。重复主循环调用不增加计数。
- 加速度窗口 >=180 mg 立即解除锁点。
- 失去新鲜有效定位期间继续按 200 ms 监测加速度，锚点最多保留至最后一次
  观察到新鲜有效定位后 10 秒。期间窗口 >120 mg、传感器失败、采样间隔
  >1000 ms、关闭过滤/GNSS 或 reset 均不保留锚点。
- 无效定位不输出“已定位”锁点。恢复有效定位且仍在保留期限内时使用旧锚点；
  超时后必须重新满足静止锁定条件。
- 新建锁点仍要求速度 <=1 km/h 且加速度平稳持续 30 秒。
  未取得锁点时持续 1–3 km/h 的弱信号场景不在本次保护范围，避免直接把
  已在缓慢行驶的设备锁死。
- 不改变 0200 调度、定位状态语义、历史补传、原始 GPS 数据或持久化格式。
  复用现有候选时间字段保存锁定后的最后有效观察时间，没有新增静态状态内存。

## 实际修改

- `src/gps_report_filter.c`、`include/gps_report_filter.h`：实现及接口说明。
- `tools/tests/gps_report_filter_host.c`：真实 C 模块弱信号/失锁回归。
- `tools/tests/test_gps_report_wire.py`：真实过滤器到 JT808 主备链路报文验证；
  为此测试补齐当前 JT808 新增依赖的局部夹具，不修改生产接口。
- 本文。构建使用独立 `build-weak-drift-20260920`，构建版本时间变为
  `20260920222619`，版本号仍为 V3.070；不作为新版本发布或交付包。

## 自动验证

`python tools/tests/test_gps_report_filter.py`：新增用例在修复前于弱信号
2.5 km/h 后锁点失效断言失败；修复后通过。覆盖 10 分钟漂移、质量/速度阈值、
传感器异常、采样中断、RMC 中断、复位、10 秒期限两侧和 tick 回绕，
以及既有真实速度/加速度释放和原始数据不变用例。

以下检查通过：

- `python tools/tests/test_gps_report_wire.py`：主备 0200 固定坐标/零速度，
  工作模式/查询及历史数据处理。
- `python tools/tests/test_feature_guards.py`
- `python tools/tests/test_stationary_location_owner.py`
- `mingw32-make.exe all BUILD=build-weak-drift-20260920`：ARM GNU 14.3 构建通过。
  Flash 105548/106496 字节，剩余 948，LOW_HEADROOM 警告。
- `mingw32-make.exe release-guard ram-guard BUILD=build-weak-drift-20260920`
  中 release-guard 通过，但整个命令因 ram-guard 失败返回 2。

构建输出见根目录 `build-weak-drift-20260920.log` 和
`build-weak-drift-20260920-guards.log`。

## 未通过与验收边界

- `test_work_mode_jt808_contract.py` 在要求旧 `no-fix-no-trusted` 日志的断言失败。
  当前未修改的 jt808.c 已使用 `fallback=unfixed` 和无历史定位报文路径；
  本次未改写该无关测试的语义。
- RAM 门禁因全程序栈证据不完整失败：missing frames=68、indirect=66、
  tail=132、internal calls=2、cycles=1。诊断静态内存 17264 字节，
  已知调用帧 2624 字节；不能据此声称 RAM 门禁通过。
- **需要实机/HIL 验证**：固定设备弱信号至少 10 分钟，观察 GPS-DRIFT
  s=3/use=1 与实际 0200；覆盖短暂/长期遮挡、真实起步、0.5–3 km/h 挪车、
  >3 km/h 行驶、休眠唤醒和传感器断开。
- 已锁点后在弱信号下极平稳地缓慢移动，可能继续使用锚点，直到出现
  加速度或足够速度/质量证据。HDOP 阈值不能识别所有多路径假定位。
  这些场景必须实测，不能用 host 测试代替。
- 未烧录、未部署、未提交，未覆盖既有交付固件。
