# A300-first ponytail audit — V3.051

范围：当前 App / Bootloader 自有源码、头文件、构建与依赖关系；扫描源码树、跨文件重复块并对照最终 ELF/MAP。第三方库只审查链接贡献，不建议机械改写。此清单只审核复杂度，不修改源码；末尾行数是净删除粗估，不是 Flash 节省承诺。

- shrink: Bootloader 内置 SHA-256 与 App 的 SHA-256 重复维护；改为两个镜像分别编译同一份 `src/sha256.c`，保留各自验签与看门狗调用。约 25 行维护代码；两个镜像仍分别需要算法，不能据此声称 App Flash 减少。[bootloader/src/image_verify.c:23](V3.051/provenance/bootloader/src/image_verify.c)
- delete: 无生产调用的 `pwr_process`、`pwr_get_state`、`pwr_request_sleep` 及对应声明；无需替代，当前工作模式直接使用 `work_mode_sleep`。约 19 行，当前 ELF 已无这三个符号，预计没有烧录体积收益。[src/power_mgr.c:17](V3.051/provenance/src/power_mgr.c)
- yagni: AGNSS 注入回调注册、默认回退及 `s_cb`；当前产品只有 `gnss_vendor_inject` 一个生产绑定，可直接调用并保留类型/数据校验。约 11 行；现 ELF 仍有 4 字节回调变量和 40 字节包装函数，不能把包装函数大小直接当作可回收字节，需重编译及同步注入测试。[src/agnss_manager.c:20](V3.051/provenance/src/agnss_manager.c)
- delete: `power_mgr.c` 中仅初始化/累计、从不用于决策或消费的旧 `s_wake` 副本；继续由 `work_mode_sleep_isr_wake` 维护真正的唤醒事件。约 3 行；volatile 访问仍可能占指令，但不得连同中断路由或 `work_mode_sleep.c` 的同名变量删除。[src/power_mgr.c:8](V3.051/provenance/src/power_mgr.c)
- delete: 里程模块仅写不读的 `s_last_hdg` 和首点赋值；无需替代，保留位置/里程计算。2 行，当前 ELF 已无该变量，预计没有烧录体积收益。[src/mileage.c:29](V3.051/provenance/src/mileage.c)

net: -60 lines, -0 deps possible.
