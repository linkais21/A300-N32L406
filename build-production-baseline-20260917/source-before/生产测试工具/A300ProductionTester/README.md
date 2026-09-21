# A300 生产测试工具 V1.5.0

配套固件：A300 标准固件 `V1.281`。工具通过 PA9/PA10 调试 UART 执行参数写入与量产功能测试。

## 串口与接线

- 115200 baud、8 data bits、no parity、1 stop bit。
- A300 PA9(TX) 接 USB-TTL RX，PA10(RX) 接 USB-TTL TX，并可靠共地。
- 断油电治具需要能直接观察外部输出端电平或负载电流，但治具无需连接电脑。

## 开始测试

1. 运行 `A300ProductionTester.exe`，选择串口并连接。
2. 新建或加载订单，填写参数、门限和可选的 `operator_id` 操作员工号。
3. 扫描 IMEI/终端 ID，写入并复检参数。
4. 工具先查询 `FACTORYCAP#`。必须得到 `VER=1`，并在下一台开始前确认断油输出为 HIGH。
5. 按表格提示切换 ACC、震动设备、操作 SOS，并观察断油治具和 TTS 声音。
6. 对断油电和 TTS 行使用“人工判定通过/不通过”完成最终结论。

## V1.281 功能测试接口

| 测试项 | 固件命令 | 自动判定 |
|---|---|---|
| 能力协商 | `FACTORYCAP#` | 要求 `VER=1` 和对应能力位 |
| 硬件 ACC | `ACCSTAT#` | 使用 50 ms 去抖后的 `DEB`，ON/OFF 各两次；`RAW/HW/LOGIC` 仅诊断 |
| G-sensor | `GSENSOR#` | 每 250 ms 读取 signed XYZ；至少两组样本且三轴总变化 >= 30 |
| 外部电压 | `STATUS#` | 使用整数 mV，按配置范围含边界判定；`ADC_NOT_READY` 在行超时内重试 |
| 断油电 | `RELAYTEST,LOW/HIGH/STATUS#` | MCU/PAD 只做诊断，最终由操作员确认治具两轮 LOW/HIGH |
| TTS | `TTS,<GBK文本>#` | 固件接受启动后，由操作员确认声音清晰可辨 |
| 调试 UART | `PARAM#` | 命令双向收发 |
| RS485 | 无 | `跳过/未测试`，不计通过且不阻断本版本测试 |

## 断油电安全流程

- 每轮只发送一次 LOW；响应不明确时查询 `RELAYTEST,STATUS#`，不会盲目重发 LOW。
- LOW 最长保持 3000 ms，固件超时自动恢复 HIGH。
- 每轮 LOW 后发送 HIGH；测试成功、失败、异常、主动断开和关闭工具时都尝试恢复 HIGH。
- 下一台设备开始前，工具必须查询并确认 HIGH。无法确认时禁止继续自动流程。
- 工具不写 `RELAYMODE`，不改变断油模式，不通过生产接口写 Flash。
- 操作员只有在治具两轮都观察到外部 LOW 和 HIGH 后才能人工判定通过。

## TTS 文本

播报文本必须为 1 到 160 个 GBK 字节，不得包含逗号、`#`、回车、换行或 NUL。工具直接发送 GBK 字节，不使用 UTF-8 自动转码。固件返回 BUSY、MODEM_NOT_READY 或 MODEM_REJECTED 时不能人工改判为通过。

## 失败分类

- `通信超时`：只读命令两次均没有匹配当前命令的完整响应。
- `固件不支持`：缺少能力位、能力版本不兼容或旧固件无命令。
- `固件/驱动失败`：当前命令返回 `Fail!` 或 MCU/PAD 诊断不一致。
- `测量值超限`：有效测量未满足门限。
- `待操作员确认`：软件路径成功，但治具/声音没有电脑反馈。
- `硬件失败`：操作员否认治具电平、电流或声音表现。
- `跳过/未测试`：本版本明确排除的 RS485。

## 测试记录

CSV 保存到程序目录 `records`，包含固件完整版本、语义版本、生产接口能力版本、工具版本、原始关联响应、失败分类、人工确认、操作员工号和时间戳。`orders` 与 `records` 是现场运行数据，升级工具时不得删除或覆盖。

## 构建

双击 `build.bat`，或执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

使用 Windows .NET Framework C# 编译器，输出为 `bin\A300ProductionTester.exe`。

## 验证状态

协议解析、命令关联、边界值与固件契约有自动化测试。ACC 电气输入、G-sensor 实际响应、ADC 精度、断油电外部电平/负载电流、TTS 声音、SOS 和断线恢复时间仍然**需要实机/HIL验证**。在 V1.281 HIL 记录完成前，不得把本候选标记为量产批准。
