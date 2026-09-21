# A300-406 V3.054 烧录验证包

N32L406CBL7 / A300-T9；硬件测试版，release_approved=false，尚未烧录，需要实机/HIL 验证。

## 烧录

- 推荐 SWD-Combined-V3054.hex，自带地址；或选择 SWD-Combined-V3054.bin，起始地址 0x08000000。二选一，执行内部 Flash 擦除、写入及校验。
- Combined 首次启动会清除外部 Flash 配置 A/B、BCR、OTA 断点及授权状态；烧录前记录设备参数，启动后恢复服务器等配置。盲区、AGNSS、Candidate/Factory/LKG 区保留。
- App-V3054.bin 位于 0x08006000，仅用于已有兼容 Bootloader 的 App 更新；一般验证请选 Combined。
- OTA-A300-406-V3054.bin 为同版 App 的平台上传包，仍需既有平台签名/授权流程，不能当 SWD 镜像烧录。同版 OTA 通常受升级版本策略限制。
- 调试串口 115200 / 8N1，核对 App V3.054、Boot 3054。

## 验证内容

1. 0x8105 消息体 64 断油、65 恢复；短信 RELAY,1# / RELAY,0#。断油保留有效定位且 0 <= 速度 < 20 km/h 的条件，无效定位、超速及多余参数应拒绝；恢复不受定位限制。先在台架验证 PA11 和继电器触点，不以软件成功应答代替物理结果。
2. 蓝灯搜星慢闪（1 秒亮、1 秒灭）、定位常亮、休眠熄灭及唤醒恢复。绿灯沿用模组控制；红灯接充电芯片 STAT，独立软件控制未实现，需确认实板接线。
3. 断网记录、重连 0x0704 补报、错误通道/旧连接 ACK 不消费记录、正确 ACK 消费、超时与掉电恢复。
4. 验证联网、定位、参数持久化、休眠唤醒、看门狗及运行内存水位。

## 本轮验证及限制

19 个相关测试脚本中 18 个通过；test_terminal_identity.py 仍失败，首个未定义符号为 service_workspace_try_acquire，既有测试桩未适配依赖。
App/Boot 全量构建、release-guard、Flash 容量检查、Boot RAM 检查和镜像结构校验通过。
完整 release-gate 因 RAM/栈证据不完整失败：静态 RAM 17900 B，已知调用帧 2520 B，未计 heap/IRQ/未知路径前剩余 4156 B；缺失帧 90、间接转移 55、尾转移 117、环 1。
App 105520 / 106496 B，Flash 剩余 976 B，有 LOW_HEADROOM 提示。本包使用当前 Makefile 默认源码构建，未采用 V3.053 交付包的临时体积优化覆盖源码，不能直接按旧包体积比较功能增量。
首次构建因 PATH 导致 Make 误选 sh 失败，显式 SHELL=cmd.exe 后重新全量构建通过；原始失败日志保留。
短信仍缺少发送号码鉴权；红灯控制未实现。不是正式发布验收通过的固件。

validation/results.json 保留实际命令和每条退出码，其余日志及 source 中的源码/构建证据可复核。本轮只更新 release_identity.json、include/config.h、include/build_version.h、tools/tests/test_release_identity_contract.py 和 tools/release_guard.py 的版本/摘要，保留已有功能改动；另新增本包和 build/delivery-v3054 打包脚本。没有提交、推送、部署或烧录。
