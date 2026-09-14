# V3.043 冷启动 Flash 识别重试测试包

仅供用户实机/HIL 验证，未批准量产。V3.042 归档未覆盖。

## 本次依据和修改

用户确认测试流程为断开外电烧录，完成后再接外电。V3.042 故障现场停在首次初始化失败后的恢复分支，初始化标志仍为 PENDING。未复位 MCU、未重新配置 SPI，仅再次调用现有 JEDEC 读取函数，即得到正确 ID 0x684015。这证明现场存在一次识别失败后无法自动恢复的问题；具体电源时序原因尚未测量确认。

bootloader/src/platform_n32l406.c 对首次初始化前的器件识别增加最多 100 次重试，每次间隔有界等待，并服务看门狗。立即成功不等待；持续失败仍禁止擦除和跳转。等待由 CPU 循环实现，实际启动耗时需要实测。

App 核心功能未修改，仅将 release_identity.json、include/config.h、include/build_version.h 的版本更新至 V3.043，并同步版本契约测试及 release_guard 指纹。新增 tools/tests/test_boot_flash_probe_retry.py，覆盖短暂失败后恢复、持续失败和立即成功。

一次性初始化范围不变：配置 A/B、BCR、OTA 检查点及授权记录。完成标志为 DONE 时正常重启和 App-only OTA 不重复清理。

## 烧录与验收

使用 V3.043/Combined-N32L406CBL7.hex，目标 N32L406CBL7。HEX 已包含 Bootloader、一次性请求及 App，无需再分别烧录。保持用户原有断外电烧录、完成后接外电的流程，烧录器供电方式按现有硬件接法执行。

先进行烧录校验，再断开调试器影响并接外电冷启动。确认设备进入 App、完成网络注册和服务器登录；在具备卫星信号的环境检查有效定位。随后再次断电上电，验证配置保留且不重复初始化。记录首次启动耗时；若仍异常，保留现场，避免先用调试复位改变故障状态。

## 已执行验证及限制

- python build/build_factory_hil_3043.py：Bootloader/App 构建、相关 host tests、Boot map、OTA、Combined HEX 和 manifest 检查通过，详见 V3.043/validation。
- python tools/tests/test_boot_flash_probe_retry.py：三类识别场景通过；修改前短暂失败场景曾失败。
- python tools/tests/test_dev_release_manifest.py --manifest artifacts/HIL-FACTORY-INIT-20260914-V3043/V3.043/SHA256SUMS-N32L406CBL7.json：通过。
- tools/flash_combined_and_selftest.ps1 对本包 BIN 的 DryRun：通过，仅验证流程，未实际擦除、烧录、复位或串口自检。
- git diff --check：通过，只有已有文件换行提示。

release-guard 通过，但 release-gate 的 RAM/栈证据门禁未通过：剩余裕量 3696 B 小于要求 4096 B，且栈证据不完整。不能把构建成功视为量产通过。

内部 DONE 字部分写入后掉电的恢复限制仍未解决。本包未完成冷启动、初始化掉电、联网、定位、正常重启及 OTA 保留配置的实机/HIL 验证，也没有自动烧录到当前设备。
