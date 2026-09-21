# 本轮自动验证记录

- `python build/build_hil_pair_20260913.py`：全量编译两个 App 和当前 Bootloader；
  版本身份、Flash 容量、真实平台公钥签名回归、Boot 静态容量、libc parser、
  OTA 包及每版 manifest 校验通过。构建无 warning/error。
- 两版 `make release-gate`：**失败**，首个失败为 RAM 预算不足；静态 17,904 B、
  已知链栈帧 2,984 B、余量 3,688 B，小于 4,096 B。全程序栈证据 incomplete。
  该结果作为试机包未获得正式发布批准的原因保留，没有调低或删除 gate。
- 定向 pytest 最终 **26 passed**，覆盖 AGNSS、堆边界、里程、JT808 身份/注册契约、
  OTA 包/平台状态机/续传、Bootloader 拒绝/恢复和 feature guards。完整命令见
  `evidence/host-regression-command.txt`。
- 独立执行 `test_jt808_first_location.py`、`test_jt808_dual_session.py`、
  `test_jt808_boot_terminal_info.py`、`test_gps_tx_bounded.py`：通过。
- `python tools/tests/test_terminal_identity.py`：完整 C99 harness 和拒绝路径通过。
  首次 pytest 为 25 passed/1 failed，原因是测试预期仍硬编码 V3.004；已改为当前
  版本契约，并将错误 revision 注入改为 JSON 字段修改，最终回归通过。
- `test_agnss_workspace_ownership.py`、`test_agnss_vendor_stream.py`、
  `test_release_identity_contract.py`：独立脚本通过。
- `python build/verify_hil_pair_20260913.py`：全文件 SHA256、OTA header/CRC、
  BIN/HEX 一致性、地址/校验和、Combined 拼接、公钥/入口及源码对照通过。
  独立 App HEX 为 ELF 导出的稀疏格式，未记录的对齐孔在 BIN 中由 objcopy 填 0；
  用户直接使用的 **SWD Combined HEX 为完整连续地址，与 Combined BIN 每字节相同**。
- `git diff --check`：通过（Git 提示换行将转换 CRLF，不是 diff-check 失败）。

V3.038 和 V3.039 的业务源码哈希相同，仅 config/build_version 版本和生成时间不同。
固件生成后再次核对 V3.039 源码输入哈希与当前工作树相同。未提交、推送、上传、
部署、重启服务、烧录或控制真实设备；没有覆盖旧版本归档。

实机上线/定位、OTA 下载签名/安装/重启、Flash 及 RAM 水位均尚未验收，
**需要实机/HIL 验证**。本机验签使用既有真实平台签名样本，不能代替新上传
V3.039 包的实际平台签名与设备验签。
