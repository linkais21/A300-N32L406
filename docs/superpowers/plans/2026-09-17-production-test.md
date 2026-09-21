# 生产测试接口补齐

范围：工具现有 14 项中排除 TTS/RS485，补齐其余测试；不扩展上一份报告中的建议抽检项目。保留现有用户改动，不提交、不烧录。

## 设计与验收

- 调试 UART 专用生产接口：FACTORYCAP VER=1；ACCSTAT 返回独立 50 ms 去抖的物理 ACC 与业务逻辑诊断；GSENSOR 返回实际 signed XYZ，失败明确拒绝；STATUS 返回有效 ADC mV；SOSSTAT 返回物理按键及连续保持毫秒数；GNSSSTAT 返回新鲜定位和完整 GSV 周期 CN 指标。TTS=0/RS485=0。
- 不扩大 PARAM 长度或短信契约：型号用已有 MODEL#，APN 只核验非敏感值和写入结果，不回显密码；GNSS 走独立查询。
- RELAYTEST 仅 UART 本地可调用，不暴露短信/JT808。HIGH 解除输出；LOW 为最长 3000 ms 的一次脉冲，重复 LOW 不续时。1 ms SysTick 只做 GPIO/计时和超时恢复；禁止进入停止 SysTick 的深睡眠；业务断油不抢占测试脉冲。MCU/PAD 仅诊断，外部输出仍人工确认。
- SOS 改为当前测试窗口内轮询，先观察释放，再连续按下达到设定时间；不根据无关联日志改判。TTS/RS485 即使旧订单启用或全选也保持排除；报告明确未测试。
- GNSS 不以 UNKNOWN 天线状态宣称开短路检测通过。使用真实有效定位/CN 质量验证接收链路，独立电气开短路不在本次能力声明中。
- 板级证据：原始 comm_board/A300-T9原理图.pdf 与 MCU 图显示 PA12=M_ACC_IN、PA2=M_SOS、PA3=CAR_ADC、PA11=OIL_CTR；与当前驱动一致，工作区旧表有冲突。本次不改 pin map。实际外部电平及治具接线需要实机/HIL 验证。
- 当前原源码基线 Flash=105520/106496 B；用户已选择将既有数学/日志/毫米量化优化合入标准源码，不修改布局或削减安全功能。

## 实施步骤

1. 保存本轮触碰文件的原始快照；增加真实 C 和 C# 回归，确认缺接口/旧判据 RED。
2. 实现有界固件生产模块、ADC 有效性和 GNSS GSV 质量统计，接入 UART/主循环/SysTick；覆盖失败、重复、超时、回绕、分包及无效数据。
3. 更新工具测试范围、SOS/GNSS 查询、MODEL/APN 复检及版本配置；提供可运行测试入口。构建使用独立目录，不覆盖现场 orders/records。
4. 定向回归：产测协议、NMEA、ADC、relay/F39、UART、硬件引脚；标准 ARM 构建及 Flash/release/RAM 门禁；检查差异，记录已有环境/证据限制。
5. 更新两端文档、匹配表和 HIL 操作要求。交付明确 host 验证与未完成硬件验收的区别。

## 执行结果

上述源码实现、定向回归、两端构建和文档已完成。最终 App 占用 100820 B，剩余 5676 B；Flash/source release guard 通过。RAM 门禁仍因完整栈/堆/异常证据不足失败，未绕过，候选不具备量产批准资格；尚需实机/HIL。详见 `docs/production-test-20260917.md`。
