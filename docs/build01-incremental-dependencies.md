# BUILD-01：App 增量构建依赖修复

对应 `build/quality-audit-20260912/REPORT.md` 的 BUILD-01。原始审计保留为历史证据。
本次仅处理 App 主 Makefile 的头文件与参数依赖；不修改 Bootloader 构建或设备运行逻辑。

## 实现

- 普通 C、SDK C、签名包装、micro-ecc 和预处理汇编统一生成 `-MMD -MP` 依赖文件，
  显式指定 `.d` 路径和对象目标，导入直接及间接头文件依赖。
- 保留签名边界的 `.o/.su` 分组规则、公钥专项依赖、Flash/RAM 门禁及链接产物恢复规则。
- 缺少 `.d` 的对象自动重编译，覆盖旧构建目录首次迁移和依赖文件丢失。
- 每个 BUILD 目录记录当前参数 SHA-256，包含编译器/objcopy 路径、C/ASM/链接参数、
  SDK/签名专用参数及源文件列表。参数变化（包括切回旧值）保守重编译全部对象并重新链接。
  Makefile 变化也使对象失效。
- 参数比较只读；`make -n` 能预览变化且不写指纹或依赖文件。无变化时不编译、不链接；
  `all` 仍按原有规则执行 size 和 Flash 检查。默认目标固定为 `all`。
- 指纹变化时显式强制对象和链接失效，避免 Windows 秒级时间戳导致快速参数切换遗漏。

## 验证

在仓库根目录执行，若 make 未加入 PATH，使用工作区工具：

```powershell
python tools/tests/test_build_dependencies.py
python tools/tests/test_flash_gate_build.py
python tools/tests/test_trust_key_build_dependency.py
python tools/tests/test_build_version_refresh.py
& ../tools/w64devkit/w64devkit/bin/make.exe -j4 all BUILD=build/build01-validation-20260913
& ../tools/w64devkit/w64devkit/bin/make.exe -n -W include/config.h all BUILD=build/build01-validation-20260913
& ../tools/w64devkit/w64devkit/bin/make.exe -B all BUILD=build/build01-validation-20260913
git diff --check
```

新增测试先在旧规则下失败：修改间接头文件后，所有对象仍显示 up to date。
修复后使用真实 GNU make 和 ARM GCC 验证五类编译规则、无变化构建、无关对象不重编译、
宏/调试/SDK/签名/ASM/链接参数变化与切回、丢失依赖文件恢复及删除旧 include。
所有夹具均在临时目录；不修改真实头文件。

完整 App 验证日志保存在 `build/build01-validation-20260913/`。首次构建 68 个对象；
`-W include/config.h` 预览及实际构建均重编译 24 个对象；无变化 dry-run 重编译 0 个。
强制全量、头文件模拟更新后的增量构建和参数切回后的 BIN 做 SHA-256 一致性检查。
上述检查通过，BIN SHA-256 为
`16fb37c995ec0952eb62fa5fd5bed9417e261e140a0ec2d596c25ed114040c3b`。
四个测试脚本、完整构建、`release-guard` 和 `git diff --check` 通过。

`make ram-guard BUILD=build/build01-validation-20260913` 返回 2：已知调用链栈帧合计
2,984 B，静态 RAM 17,820 B，扣除两者后的 3,772 B 小于所需 4,096 B；
仍缺少完整栈/堆/异常边界证据。这是独立 RAM 门禁失败，未放宽规则。
Flash 门禁通过但报告 `LOW_HEADROOM`，占用 105,808 / 106,496 B，余量 688 B；
`CONFIGURATION_CHANGED` 表示与冻结基线配置不可直接比较，不将 +32 B 归因本次修复。

## 边界

发布/CI 仍保留 `-B`。工具在原路径被替换、系统头文件变化、保留旧 mtime 的文件恢复，
以及同一个 BUILD 目录内同时启动多个不同配置的 make 进程不在保证范围内；前几项应全量构建，
并发不同配置应使用不同 BUILD 目录。单个 `make -j4` 已验证。

当前 Flash 余量仍低，RAM 运行时证据独立验收。本次没有烧录、部署或执行完整发布脚本；
设备运行行为仍需要实机/HIL 验证。不能据此宣称 RAM/Flash 容量问题已经解决。
