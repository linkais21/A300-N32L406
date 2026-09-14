# V3.042 分别烧录后未启动：实机诊断

本轮实机 SWD 读回 Bootloader 与 App 均与 HIL-FACTORY-INIT-20260914-V3042
归档 BIN 逐字节一致。首次快照 PC=0x20000078，MSP=0x200008C0，内部
0x08005818 completion=0xFFFFFFFF；目标参考电压约 3.295 V。
这排除了第二次烧录擦掉 Bootloader 的假设。

J-Flash 本机保存配置 Default.jflash 显示 ChipName=Nations N32G455RE、
AutoPerformsStartApp=0、NumExitSteps=0。它与实际 N32L406CBL7 型号不符，且
未配置自动启动。当前 GUI 未保存状态未直接读取，不能把保存配置等同于完整 GUI 快照。
另发现前次诊断遗留 GDB 进程仍等待旧地址擦除脚本；已结束该诊断进程。

未重新烧录、未通过调试器直接擦除外部 Flash。执行一次 SYSRESETREQ 并运行后：
- 两秒后 PC=0x080062AE，位于 App delay_ms。
- completion=0x444F4E45（DONE），Bootloader 已执行首次初始化并跳转 App。
- 后续快照 uptime=73327 ms，PC=0x08016A32，仍在 App。
- EC800M state=6（READY）、registration=1、SIM identity ready=1、failure=0。
- JT808 主会话 channel=0、state=3（ONLINE）。
- GNSS valid=1；RX=48073、GGA=62、RMC=61、CS=0、FMT=0、DROP=107。
  DROP 非零需在后续稳定性测试观察，不能宣称串口接收完全无丢弃。

状态地址依据本包 ELF 符号与反汇编核对。未输出真实身份、坐标或凭据。
COM6/COM24 监听 45 秒均 0 字节；本轮未获得 UART 启动日志，上述为 SWD 状态证据。

生产流程应使用匹配 N32L406CBL7 的工程，完整写入和校验后执行 reset/start application。
推荐 Combined HEX；如分开写，保持 MCU 停止直到两份均写好再复位。
外电一直连接不代表发生过复位；板载电池或其他供电也可能使断开外电不构成冷启动。
真正断电重启、调试器拔除后的启动、量产编程器兼容性及 DONE 部分写入掉电恢复
仍需实机/HIL 验证。已有 RAM 发布门禁问题仍未关闭。
