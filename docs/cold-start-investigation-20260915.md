# 首次上电无响应：固件排查（2026-09-15）

## 结论边界

用户确认烧录文件为 `artifacts/HIL-STABILITY-20260915-V3049-RETRY/SWD-Combined-V3049-RETRY.hex`，并保留了红灯亮、蓝绿灯灭、串口无输出的故障现场。随后通过 SWD 无复位连接完成现场采集，定位为 Bootloader 镜像选择返回后的恢复循环。首次全零读取的底层原因仍待区分。本轮未修改固件、生成发布包或烧录；执行了短暂停核/恢复、内存读取，以及借助当前 SPI 配置的只读 NOR 事务。

## RETRY 故障现场：已实测

- VTref=3.295 V，仅说明采样时调试参考电压，不能代表上电波形。
- PC=0x08001A3E，LR=0x0800004D，VTOR=0x08000000：停留于 `boot_recovery_step()`，来自 `bootloader_select_image()` 返回后的永久循环。
- CFSR/HFSR=0；RCC CTRL=0x03008B43、CFG=0x0018250F：当前 PLL 已就绪并被选中。CTRLSTS=0x0C00496E，记录 POR/PIN，未见 IWDG/WWDG 标志。这次现场不支持时钟等待或异常复位是当前卡点。
- 0x08005818=0x444F4E45：工厂初始化已经 DONE。
- 内部 Flash 读回 129232 字节，除 DONE 的四字节外逐字节匹配用户指定 RETRY Combined BIN，App 完全一致。排除当前镜像漏烧/错包这一解释。
- 按匹配 ELF 的栈帧定位，`bcr_load` A/B 缓冲区位于 0x20005B28/0x20005B50，各 40 字节均为零。这些是函数返回后的栈残留，不是每一次重试的完整轨迹，不能据此宣称已观察到每次读操作。
- 不复位、不重初始化 SPI，保持 CPU 在原恢复循环中运行，通过 SWD 对 SPI DAT 和既有 PA4 CS 寄存器操作，只发送 0x9F/0x05/0x03 只读命令：JEDEC=0x684015，状态=0x00，两份 BCR 各 40 字节均为 0xFF。没有发 WREN、擦除、编程、Flash reset 或掉电模式命令；事务结束 CS 恢复高。
- 最后 DHCSR=0x01010001，CPU 未保持 halt；仍执行原恢复循环。没有跳过校验、手动跳 App 或重试镜像选择。

**现场结论：** BCR 目前是正常空白态，但启动留下的是异常全零读取结果；Bootloader 错误路径没有再次读取或退出恢复循环。这解释了即使 Flash 当前已可读，设备仍无 App 日志、蓝绿灯不工作的现象。连续三次无间隔校验重试未关闭问题。当前 SWD 事务显著拉长字节/CS 间隔，而且发生在上电很久后，不能用它单独区分电源稳定时间与连续传输时序问题，也不能认定只增加重试次数就足够。

下一步应针对生产 `boot_ext_read` 的传输节奏补充可控诊断/回放，并记录每次原始结果、就绪判断和间隔；确定时序因素后再实现有界恢复。真实无效 BCR 必须继续拒绝启动，不能把全零一概当作空白或直接绕过。

原始现场证据保存在工作区 `tmp/swd-v3049-diag/retry-live-*`，其中栈快照及 Flash 读回只作为本地诊断资料，不提交。新增 J-Link 脚本没有复位/烧录命令；只读 SPI 脚本会写外设传输寄存器，不能称其为完全无扰动采集。

初始检查对象为当前工作树（HEAD 6eab8e6，含用户已有大量未提交修改），随后补充了以下烧录文件核验。当前 Makefile 的 Bootloader 与 App 均使用 SYSCLK_SRC=3，即内部 HSI PLL、64 MHz；外部晶振启动延时不是当前主时钟链路的直接解释。

## 用户指定 RETRY 镜像的核验

- HEX SHA256：`856B811196BED0CC3EA4C0B109054562C60E94527EE29D91AEA5C7647BA5D5B7`。
- Intel HEX 记录校验和正确，有效地址 `0x08000000..0x0801F8CF`，所有装载字节与同目录 Combined BIN 相符；独立 Bootloader HEX 与 Combined 相符。
- 将 `bootloader/build/bootloader.elf` 用 ARM objcopy 转为临时 BIN，22556 字节逐字节匹配 RETRY 镜像的 Bootloader。下述反汇编地址因此适用于指定文件；尚未对设备 Flash 实际读回。
- App 区与原 V3.049 Combined/App BIN 完全相同。RETRY 变更在 Bootloader 区域。
- `bcr_load` 的机器码确有三次重试，但 `0x080000FA` / `0x080000FE` 在读取失败时直接跳到 `0x080000D4` 返回 IO_ERROR；不会进入下一次重试。
- `main` 在工厂初始化失败后循环于 `0x08000026`，复位记账失败后循环于 `0x0800003A`，镜像选择返回后循环于 `0x08000048`。公共空转函数为 `0x08001A34`，喂狗为 `0x08001A24`。故障态若停在公共函数，可结合 LR 区分调用路径。
- PLL 就绪无限等待为 `0x08002B1A..0x08002B1E`；PLL 切换无限等待为 `0x08002B30..0x08002B38`。这些缺口在 RETRY 的实际机器码中仍存在。
- 镜像内 `0x08005818` 为 `0xFFFFFFFF`（PENDING），所以完整烧录该文件后的第一次启动仍必须完成工厂初始化，不能只考虑 BCR 重试。

## 已确认的启动缺口

1. **Bootloader 失败会停留在无诊断、持续喂狗的循环。**
   `bootloader/src/main.c` 中工厂初始化错误、试运行复位记账失败、镜像选择返回，最终均进入恢复循环。`boot_recovery_step()` 实际仅有限空转，没有重读、重选镜像或故障输出。该循环因此不会因外部 Flash 随后稳定而恢复，也不会通过 IWDG 自动复位。
   `factory_init_apply()` 对首次探测、擦除、读回或 DONE 写入失败返回错误；这些检查是事务安全要求，不能直接绕过进入 App。

2. **已有冷启动重试没有覆盖所有 NOR 失败。**
   `boot_ext_device_valid()` 有 100 次 JEDEC 探测；但工厂初始化已经 DONE 时直接跳过这一步。`boot_platform_init()` 只做一次探测并忽略结果。
   `bcr_load()` 的三次循环仅覆盖读取成功但两份记录都无效、且不是全擦除态的情况。任一读取返回 false 就立即返回 IO_ERROR，不重试。`bootloader_select_image()` 随即失败，落入上述永久恢复循环。这是“供电瞬态读取失败后，必须再次复位才能重试”的确定代码路径；现场是否发生该读取错误尚未证明。

3. **SystemInit 中 PLL 等待无上限，早于可见诊断。**
   SDK `system_n32l40x.c` 的 PLLRDF 等待及 SCLKSTS 切换等待没有超时。Bootloader 在设置看门狗、UART、LED 之前执行它；如果状态一直不满足，软件无法自行恢复。App 也执行该函数；经 Bootloader 启动时已有 IWDG，行为不能与独立 App 启动混为一谈。
   HSI 有启动超时，但失败后返回 MSI 路径；App 仍按固定 64 MHz 初始化 SysTick，不能把该返回当作完整降级策略。Bootloader 又在 SystemInit 之后初始化 .data，会覆盖其中对 SystemCoreClock 的失败赋值。

4. **App 的早期诊断仍有空窗。**
   `hw_adc_init()` 中 ADC 校准为无超时等待，发生在 App 的 `hw_iwdg_init()` 和版本/复位横幅之前。经 Bootloader 启动时可能由继承的 IWDG 复位；没有 Bootloader 的情况下则不能依靠 App 尚未启动的看门狗恢复。
   Bootloader 的 UART 进度只在镜像安装时启用，不能据“无串口日志”判断复位入口完全未执行。

## 已检查但不能据此认定根因的项目

- App 的 .data 复制、.bss 清零、SystemInit、构造函数、main 调用链存在，边界由链接脚本给出；未发现漏做 .bss/.data 初始化的直接证据。
- Bootloader 先 SystemInit 再初始化 C 数据，与 App 顺序不同；其向量表只有初始 MSP 和 Reset_Handler，缺少有效异常诊断入口。需单独处理，但没有证据证明本次是异常触发。
- 历史 `v3042-post-program-start-diagnosis.md` 记录的是烧录后 CPU 停在 SRAM、复位运行后正常，并未关闭真正冷启动验收；不能用那次成功解释这次反复上电故障。
- 指示灯不亮、整机电流表接近零，不足以区分 MCU 未执行、Bootloader 空转、App 尚未打开大负载。

## 下一次故障要保留的证据

先记录确切版本、文件名、Combined HEX/分开烧录/OTA，以及是否连着调试器。若只更新 App，Bootloader 中的修复不会更新。

故障出现后不要先断电、复位或重新烧录。使用不自动复位的 SWD attach，记录 PC、LR、MSP、xPSR、VTOR、CFSR/HFSR、RCC CTRL/CFG/CTRLSTS，以及内部 0x08005818 的工厂初始化 completion。停止/连接调试器会扰动运行，记录连接方式；不要输出设备身份、配置或凭据。用实际烧录包对应 ELF 解析 PC，不能套用其他版本地址。

- PC 在 PLL/时钟切换等待：优先验证有界时钟启动和失败诊断。
- PC 在 Bootloader 恢复循环：继续辨认工厂初始化/BCR/镜像校验失败阶段；不能只删除失败保护。
- PC 在 ADC 校准：验证有界校准及故障恢复。
- PC 在 SRAM 或调试暂停：核对本次编程器型号、reset/start 和供电是否真正掉到复位条件。

后续诊断固件应覆盖时钟前后、工厂初始化、BCR 读取、App 入口、ADC 前后，采用有界输出或可读阶段记录；PD0 指示必须先核实有效电平。恢复重试必须有上限，保留 factory/BCR/OTA 校验，不用无限复位或任意新增延时掩盖错误。

## 本轮验证

在 A300-first 下 fresh 执行：

- `python tools/tests/test_boot_flash_probe_retry.py`：PASS。
- `python tools/tests/test_bootloader_factory_init.py`：PASS。
- `python tools/tests/test_reset_diag.py`：PASS。

这些测试分别验证探测重试、工厂事务及复位记录；不证明完整启动链在瞬态失败后恢复。尤其工厂测试由测试代码再次调用初始化，生产 main 出错后并不会再次调用。

未执行固件构建：本轮没有固件代码改动。未执行烧录、部署或主动冷启动复现；已对用户保留的故障态进行上述 SWD 采集。需要实机/HIL 验证：连续传输与慢速读取对照、不同冷启动稳定时间、修复后的不接调试器启动、首次工厂初始化及外部 Flash 瞬态故障恢复。
