# 2026-09-18 参数下发现场问题

输入：工作区 `ReceivedTofile-COM13-2026_9_18_15-35-04.TXT`；设备日志版本 V3.059。
用户补充的原始命令：`APN,cmiot,,#`、`FREQ,10,60#`。

## 结论与修改

1. **PID/FIP 文本下发反馈**：原 0x8300 路径先保存并执行重连/重新注册，再发送 0x0001。PID 已变化时应答报头也使用新号码，无法保证平台关联原请求。本轮改为保存结果确定后，先在原通道按请求号码及流水号应答，再执行重连、PDP 重启、重新注册或安排复位。保存失败仍回失败，不执行配置副作用。应答发送失败不无限等待，已保存的配置继续生效。没有增加非标准文本透传上行。
2. **APN**：用户给出的文本命令在当前源码可正常执行，实际 EC800M host 链路生成 `AT+QICSGP=1,1,"cmiot","","",0`，退出 AUTO 并重启 PDP。不能把另一入口的问题当作这条文本命令的已确认根因。本轮同时修复标准 0x8103 APN 参数仅保存字符串、不切换 AUTO、不重启 PDP 的缺陷；应答先于 PDP 重启，重复相同参数不重复保存/重启，保存失败无运行态副作用。现场 APN 不生效仍需复测。
3. **车牌“粤”乱码**：原日志第 237 行的车牌前缀为 GBK，CAR 修改后的第 1073、1264 行为 UTF-8；按 GBK 显示后呈现“绮…”等字。保留原持久化格式，复用省份编码表，统一 CAR 查询、启动日志和 JT808 上报为 GBK。测试覆盖 UTF-8/既有 GBK 输入及 JT808 查询、注册报文。尚未确认用户看到乱码的具体界面；此结论针对日志已证实的显示编码问题。
4. **10/60**：F39 范围允许该值；实际 cfg_query → at_config → F39 → 保存路径对 `60/300`、`30/180`、`20/120`、`10/60` 均通过。日志第 2107、2148 行出现 CFGQ 失败，但没有下发原文，不能将失败定位到特定命令。新增脱敏诊断 `pending=0`、`reject=PASS_SHAPE`、`pass_bytes=… accepted=…`，不输出 APN 密码、Key 或完整 Pass。未修改间隔范围，也未声称现场故障已解决。

## 验证与限制

- 新增回归先复现了 PID 应答号码错误、0x8103 APN 自动模式未关闭及 CAR GBK 查询失败，修改后通过。
- 18 个定向 host 脚本通过：`test_jt808_params`、`test_jt808_params_wire`、`test_jt808_text_command`、`test_text_ack_order`、`test_car_reply_encoding`、`test_at_config_serial_f39`、`test_f39_actions`、`test_f39_config`、`test_f39_parser`、`test_f39_dualset`、`test_f39_end_to_end`、`test_cfg_query_f39`、`test_cfg_query_pass`、`test_cfg_query_lifetime`、`test_terminal_identity`、`test_feature_guards`、`test_jt808_dual_session`、`test_remote_relay`。入口均为 `python tools/tests/<name>.py`，host GCC 通过 PATH 指定工作区 w64devkit。
- `python tools/release_guard.py` 与本轮文件的 `git diff --check` 通过。身份门禁仅更新已人工核对的 main 车牌日志和 F39 接口摘要；身份派生和拒绝路径检查保留。
- **固件链接失败，未生成交付固件**。ARM GNU 14.3.1，使用 Makefile 默认配置，保留当前版本头，独立 BUILD 目录运行 `make.exe SHELL=cmd.exe -o include/build_version.h BUILD=build-field-config-20260918 all ram-guard`。最新源码占用 107756 B，超出 104 KiB App 分区 1260 B；RAM 链接报告 20840 B，不等同于栈/堆验收。链接失败导致 ram-guard 未执行。
- 修改前源码的隔离对照同一默认配置占用 106964 B，已超限 468 B。另按 V3.059 已有的 `SIZE_FLAGS=-Os -finline-limit=128` 配置验证本轮源码，仍超限 948 B。未更改 Makefile、Flash 分区、安全功能或版本号来绕过容量门禁。
- 初次 host GCC 未找到汇编器、make 误用 sh 的环境问题，分别通过补齐工具链 PATH、显式 `SHELL=cmd.exe` 排除；之后上述容量失败是真实链接结果。
- 证据（包括原始源码快照、对照构建和测试日志）位于 `build/field-config-20260918/`。其中子目录保留运行时名称，日志中的原始 BUILD 路径对应移动前位置。

## 本轮文件

- 行为：`src/at_config.c`、`src/cfg_query.c`、`src/f39_reply.c`、`src/jt808.c`、`src/jt808_params.c`、`src/main.c`。
- 接口/复用：`include/at_config.h`、`include/f39_reply.h`、新增 `include/plate_encoding.h`。
- 验证：`tools/release_guard.py`；新增 `tools/tests/test_text_ack_order.py`、`tools/tests/test_car_reply_encoding.py`；更新 `test_jt808_params.py`、`test_jt808_params_wire.py`、`test_jt808_text_command.py`、`test_cfg_query_f39.py`、`test_terminal_identity.py`、`test_f39_end_to_end.py`。
- 文档：本文件。保留所有原有未提交修改；未提交、推送、烧录、部署或覆盖已有交付固件。

## 待完成

先解决当前工作树的固件容量阻塞，再生成具有独立版本身份的测试包。之后**需要实机/HIL 验证**：两平台的 PID/FIP 结果关联、APN 修改后的 PDP/网络恢复及复位保持、车牌实际显示与上报、日志平台准确下发 `FREQ,10,60#` 后的回读/复位保持/实际报文间隔。host 测试不能替代这些结论。
