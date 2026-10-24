# A300-406 V3.094 公共路径优化独立测试版

本包是待实机验证的 App 优化试验版，未正式发布、未合入主仓库、未上传平台、未烧录。未加入 RTK。

## 实测结果

| 项目 | 冻结基线 | 本测试版 |
|---|---:|---:|
| App 占用 | 106336 B | 106236 B |
| App 预算 | 106496 B | 106496 B |
| App 剩余 | 160 B | 260 B |
| 静态 RAM | 15964 B | 15964 B |
| 堆预留 | 1024 B | 1024 B |
| 启动/主路径栈预算 | 2812 B | 2812 B |
| 嵌套异常预算 | 584 B | 584 B |
| RAM 预算间隙 | 4192 B | 4192 B |

净节省 **100 B**。尚未达到 4 KiB 应用增长余量目标；维持“不达标不合入”的约定，不据此推进 RTK。Flash 剩余是代码增长容量，不是运行中逐渐消耗的 RAM；本包不构成长期无溢出/无死机证明。

## 改动范围

只在 source-optimized 中修改 src/at_config.c、src/ec800m.c、src/f39_reply.c：紧凑固定串口命令名称表，共用查询结果/截断失败处理，TCP/UDP 同格式发送与关闭命令字符串共用。命令内容、参数范围、单位、配置保存、继电器安全条件、权限和 ACK/副作用顺序保留。

未修改 Makefile、编译选项、版本身份、Bootloader 源码/二进制、链接脚本、App 起址、内外 Flash 布局、OTA 验签/信任锚/包契约、BCR、factory/LKG/rollback 和持久化格式。生产目录的源码与默认构建产物均无本轮写入；哈希核对见 evidence/production-verification.json。核对期间主目录一个既有测试脚本由其他工作更新，本轮未改该文件，差异如实单列。

试验记录：广义参数 span/复制共用增加16 B，拒绝；数字读取共用增加64 B，拒绝；大端读取共用无净收益，拒绝；端点分支共用无净收益，拒绝。精简参数复制共用曾省32 B，但最坏栈增加8 B，已撤回。仅保留最终组合有益且 RAM/栈不恶化的三处源码改动。试验中间产物均为审计材料，不作为用户烧录入口。

## 文件与使用边界

- firmware/*-App.hex：仅 App，Intel HEX 已带 0x08006000 起址。
- firmware/*-App.bin：仅 App，加载地址 **0x08006000**；不能按0地址加载。
- firmware/*-App.elf / .map：与交付 BIN 绑定的调试及容量证据。
- firmware/*-OTA-UNSIGNED.bin：32 B 原契约传输头加同一 App，仅供后续平台签名/契约验证；**尚未签名，不可直接作为可安装 OTA 包，也不是可烧录 App BIN**。
- source-baseline：冻结时的完整构建输入副本（含原有未提交修改，不是 Git HEAD）。
- source-optimized：独立优化源码与验证工具；源码补丁 optimization.patch，测试环境修复 test-environment.patch。
- evidence：每项构建、门禁、测试、差分回放和哈希记录。

现有设备验证应保留原 Bootloader、配置及恢复镜像，不执行全片擦除；仅使用 App 对应的应用区更新流程。包内不提供 Combined/整片镜像。需要按设备现有启动契约验证安装、试运行确认及回退。

版本身份刻意冻结为 V3.094 / 3094，用于同输入尺寸比较。设备控制台不会显示另一个优化版本号，必须用本包路径和 SHA256 识别；已是3094的设备可能按正常版本策略拒绝同计数OTA。未修改平台或绕过版本校验，正式/远程试投前必须单独分配版本、重新构建和签名。

## 已自动验证与局限

ARM GNU Toolchain 14.3.Rel1 全量构建无编译警告，release-gate 通过；Flash门禁仍提示 LOW_HEADROOM。门禁内的历史容量参考配置不同，delta不可当作本轮收益；本轮收益只使用本包冻结基线106336 B对比。

78 项相关 host 测试通过且无 SKIP，覆盖 F39/串口/0x8300、JT808 参数、配置查询、EC800M、FOTA续传/掉电/验签和Boot旧镜像/LKG恢复等。6,244组F39和2,208组串口输入各覆盖保存成功/失败，每个版本16,904次执行逐字节对比一致；包含配置、应答及副作用/调用参数。它们是主机编译执行/模型/源码契约验证，不是实际 ARM 时序或实机运行证明。

初次 host 回归出现中文目录嵌入C代码时的ASCII编码异常、跨仓库配置路径缺失，以及冻结测试仍期望旧四参调用。仅在独立验证副本修复UTF-8/测试环境路径，并让调用契约严格包含当前真实第五个里程参数；未更改产品业务或放宽断言。修复补丁随包提供。

基线的参与编译文件已逐项核对原始SHA256。一个并行更新的测试夹具在环境修复后按原四参断言重建，未声称其原始混合换行字节已恢复；详情单列于baseline-snapshot-verification.json。这不涉及固件编译输入。

栈工具的独立报告仍为 INCOMPLETE（3个缺失帧、1个间接转移、29个尾转移、2个内部调用），项目已审查执行根RAM门禁通过。不能将其表述为全程序栈上界已证明。

**需要实机/HIL 验证**：出货旧Boot/旧App起点的OTA安装、确认、失败/掉电回滚；原定位、里程、主备平台、休眠、盲区与AGNSS混合负载；长期采集HEAP_USED、STK_PEAK、RAM_GAP和复位原因。只有你验收完成并明确授权后再考虑正式版本合入/发布。

## 独立复现

在 source-optimized 目录执行（MakeExe与ToolchainDir指向本机已安装工具）：

```powershell
& $MakeExe -j4 all -o include/build_version.h BUILD=build-common-final TOOLCHAIN_DIR=$ToolchainDir
& $MakeExe release-gate -o include/build_version.h BUILD=build-common-final TOOLCHAIN_DIR=$ToolchainDir
```

固定版本文件必须保留 `-o include/build_version.h`。以上只在源码副本生成产物，不应在主仓库执行本包试验命令。主机跨仓库身份测试如需执行，设置 A300_VALIDATION_WORKSPACE 为实际工作区根目录，或提供相同的只读平台配置证据。
