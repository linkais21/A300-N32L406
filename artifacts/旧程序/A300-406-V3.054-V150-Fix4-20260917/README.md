# A300 V1.5.0 联调 Fix4

继续使用原 A300ProductionTester.exe V1.5.0，不替换 EXE。完整固件保留 Fix3 的优化、APN、6F ICCID、盲区存储及编译时间修复。

## 烧录与测试

使用 SWD-Combined-N32L406CBL7.hex（自带地址）；若使用 BIN，起始地址 0x08000000。二者选一，写后校验再复位。完整镜像首次启动会重置配置及升级状态，请先保存参数，再重新写入。App 位于 0x08006000，不能把完整 BIN 写到 App 地址。

- G-sensor 回包增加真实 PB3 的 INT 字段，供原 EXE 解析；测试时按提示晃动设备。通过解析不等于已通过实机运动测试。
- SOS 回包增加 LEVEL=LOW/HIGH 和 ACTIVE=1/0，保持 DOWN/HOLD_MS。测试时拉低 SOS（PA2）；原 EXE 检测有效低电平，不据此宣称验证了持续时间或释放动作。
- GPS 已定位但 C/N 为零的根因尚未确认，不伪造 C/N 或降低门限。新增 GNSSDIAG# 计数及 GNSSRAW# 限时语句输出。输出位于 MCU 接收队列之后，并非硬件 UART 无损抓包；队列丢失可用计数辅助识别。
- TTS、RS485 不勾选。旧工具继电器行的自动通过不代表负载实测通过。

## 保存诊断日志

先断开生产测试工具串口，再在本包目录运行（COM12 按实际修改）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\capture_production_diag.ps1 -Port COM12
```

保持设备通电和 GPS 接收，采集期间将 SOS 保持低电平。15 秒后自动关闭串口，原始接收字节保存到 diagnostic-logs 下新建的时间戳文件，不覆盖旧日志。此日志可能含真实位置等信息，分享前脱敏。脚本不执行继电器或配置写入。固件单次原始语句输出最多 32 条/5 秒，默认关闭。采集后可重新连接原测试工具。

## 验证与限制

真实 C 回放覆盖 GSV 完整周期、交错、重复、坏校验、过期、计时回绕及诊断输出上限；原 V1.5.0 EXE 的实际解析器验证固件 G-sensor/SOS 回包。具体结果见 validation。所有 GPIO、GNSS、串口采集、盲区与平台上报均需要实机/HIL 验证。

完整发布门禁仍因全程序栈/堆/异常上界证据不完整失败，本包仅为样机测试候选。test_terminal_identity.py 仍存在既有测试夹具缺依赖的链接失败，不计为通过。GPS 实机 C/N 问题尚未关闭。

本轮文件：src/production_test.c、src/gps.c、include/gps.h；tools/tests/test_production_test.py、test_production_gnss.py、test_v150_binary.ps1；tools/capture_production_diag.ps1；本文及生成的编译时间与交付包。原 EXE、配置、订单、记录均未修改。
