# A300_406 JT808 双通道注册上线定位实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 N32L406 固件上实现 JT/T 808-2013 主、备双通道独立注册鉴权和可信实时定位上线，并修复阻断链路的 I2C2 AF 与 EC800M 注网响应边界。

**Architecture:** 保留现有 `ec800m → tcp_manager → jt808 → gps/flash_config` 分层；新增两个很小的纯 C 边界模块：`ec800m_at_response` 负责完整 AT 行结束及注册状态解析，`jt808_session` 负责单通道无 I/O 状态转换。`jt808.c` 只编排帧、存储和逐通道路由，不整体移植 N32G452 参考工程。

**Tech Stack:** C99、ARM GNU Toolchain 14.3、N32L40x SPL、Python 启动的 host-C harness、Make、BY25Q16 NOR Flash。

## Global Constraints

- 协议固定为 JT/T 808-2013；消息头为 12 位终端手机号的 6 字节 BCD，不加入 2019 版协议标识。
- 合法 PID 为 11 位十进制数字；PID 为空时由合法 15 位 IMEI 末 11 位派生并在使用前成功持久化。
- 主、备服务器各自拥有注册、鉴权、TCP generation、重试、退避和鉴权码；任何应答不得跨通道推进状态。
- 注册/鉴权间隔 5 秒，每轮最多 3 次已发出尝试，耗尽后退避 60 秒。
- 实时 `0x0200` 只使用新鲜有效 GNSS 坐标和合法日期时间；不把零坐标、过期坐标或冻结坐标标成有效定位。
- 不扩大外部 Flash 分区，不整体移植 N32G452 的低功耗、RTC、定位完整性或大型 JT808 实现。
- ISR 不增加阻塞、Flash 写入、动态分配或复杂解析；所有等待和重试保持有界。
- 保留用户现有工作树改动；不提交、不推送、不烧录、不启动长期服务。
- 每个生产改动前必须先运行对应新测试并观察预期失败；测试失败原因必须是缺少目标行为而非编译夹具错误。

---

## 文件结构

### 新建

- `include/ec800m_at_response.h`：完整 AT 事务结束与 `CEREG/CGREG` 状态解析的纯函数接口。
- `src/ec800m_at_response.c`：不依赖 UART/DMA 的 AT 响应解析实现。
- `include/jt808_session.h`：单通道 JT808 会话状态、事件和动作接口。
- `src/jt808_session.c`：不做 I/O/Flash 的注册鉴权状态转换。
- `tools/tests/test_ec800m_netreg_transaction.py`：分片 AT 响应 host-C 测试。
- `tools/tests/test_flash_config_v3.py`：模拟真实 NOR 1→0、擦除和每个写入切点的配置 v3 测试。
- `tools/tests/test_jt808_dual_session.py`：双通道帧级注册鉴权、错通道/旧 generation 测试。
- `tools/tests/test_jt808_first_location.py`：首次有效定位和逐通道路由测试。

### 修改

- `include/config.h`：I2C2 AF6。
- `src/hw_init.c`：I2C2 注释与 AF 契约一致。
- `src/ec800m.c`：等待完整 `OK/ERROR` 后解析注册状态；去除敏感身份启动日志。
- `include/flash_config.h`、`src/flash_config.c`：v3 双鉴权码、generation、commit marker、v1/v2 迁移。
- `include/terminal_identity.h`、`src/terminal_identity.c`：完整 PID/IMEI 身份解析和成功持久化。
- `include/jt808.h`、`src/jt808.c`：双会话编排、逐通道发送、应答绑定和定位门控。
- `src/main.c`：初始化不再复制单一鉴权码到一个全局会话；主循环先推进 TCP 再推进 JT808。
- `Makefile`：加入两个新纯 C 模块。
- `tools/tests/test_hardware_pin_contract.py`：AF6 合同。
- `tools/tests/test_terminal_identity.py`：11 位 PID 持久化与 12 位消息头。
- `tools/tests/test_flash_config_migration.py`：保留 v1/v2 迁移覆盖并适配 v3。
- `tools/tests/test_ec800m_netreg_freshness.py`、`tools/tests/test_jt808_registration_tx.py`：从源码文本合同降为补充检查或删除被行为测试覆盖的断言。
- `README.md`：记录 JT808-2013 身份、双平台会话和实机验证要求。

---

### Task 1: 修复 I2C2 AF 与 EC800M 注网事务边界

**Files:**
- Create: `include/ec800m_at_response.h`
- Create: `src/ec800m_at_response.c`
- Create: `tools/tests/test_ec800m_netreg_transaction.py`
- Modify: `include/config.h:96-99`
- Modify: `src/hw_init.c:285-327`
- Modify: `src/ec800m.c:228-274,481-508`
- Modify: `Makefile` source list
- Modify: `tools/tests/test_hardware_pin_contract.py`
- Modify: `tools/tests/test_ec800m_netreg_freshness.py`

**Interfaces:**
- Produces:
  - `ec800m_at_end_t ec800m_at_response_end(const char *data, uint16_t length)`
  - `bool ec800m_parse_reg_status(const char *data, const char *prefix, int *status)`
- `ec800m_at_response_end` 只认可完整行 `\r\nOK\r\n` 或 `\r\nERROR\r\n`；裸前缀和不完整终止行返回 `EC800M_AT_PENDING`。

- [ ] **Step 1: 编写 I2C AF6 和 AT 分片失败测试**

`test_ec800m_netreg_transaction.py` 编译真实 `src/ec800m_at_response.c`，使用手工字面量覆盖：

```c
assert(ec800m_at_response_end("\r\n+CEREG:", 10U) == EC800M_AT_PENDING);
assert(ec800m_at_response_end("\r\n+CEREG: 0,2\r\nO", 18U) == EC800M_AT_PENDING);
assert(ec800m_at_response_end("\r\n+CEREG: 0,2\r\nOK\r\n", 21U) == EC800M_AT_OK);
assert(ec800m_parse_reg_status("\r\n+CEREG: 0,2\r\nOK\r\n", "+CEREG:", &status));
assert(status == 2);
assert(ec800m_parse_reg_status("\r\n+CGREG: 0,5\r\nOK\r\n", "+CGREG:", &status));
assert(status == 5);
assert(!ec800m_parse_reg_status("\r\n+CEREG:\r\nOK\r\n", "+CEREG:", &status));
```

将 `test_hardware_pin_contract.py` 的编译夹具断言改为：

```c
_Static_assert(BSP_I2C_GPIO_AF == GPIO_AF6_I2C2,
               "PD14/PD15 I2C2 must use AF6");
```

- [ ] **Step 2: 运行 RED**

Run:

```powershell
python tools/tests/test_ec800m_netreg_transaction.py
python tools/tests/test_hardware_pin_contract.py
```

Expected: 第一个因头文件/函数不存在失败；第二个因当前 AF1 不满足 AF6 失败。

- [ ] **Step 3: 实现纯响应解析和 AF6**

接口定义：

```c
typedef enum {
    EC800M_AT_PENDING = 0,
    EC800M_AT_OK,
    EC800M_AT_ERROR,
} ec800m_at_end_t;

ec800m_at_end_t ec800m_at_response_end(const char *data, uint16_t length);
bool ec800m_parse_reg_status(const char *data, const char *prefix, int *status);
```

`ec800m_at_response_end` 按完整 CRLF 行扫描，不能用对整个缓存的裸 `strstr("OK")`。`ec800m_parse_reg_status` 接受 `<n>,<stat>`，要求 `n` 和 `stat` 均成功解析且 `stat` 在 `0..5`。

修改：

```c
#define BSP_I2C_GPIO_AF GPIO_AF6_I2C2
```

`state_machine_netreg()` 对 `CEREG?` 和回退 `CGREG?` 都等待 `OK`，再调用纯解析器；收到 `ERROR` 或格式非法时回退/保留 `-1`。

- [ ] **Step 4: 运行 GREEN 和相关回归**

Run:

```powershell
python tools/tests/test_ec800m_netreg_transaction.py
python tools/tests/test_hardware_pin_contract.py
python tools/tests/test_ec800m_netreg_freshness.py
python tools/tests/test_ec800m_health_observability.py
python tools/tests/test_i2c_bus_recovery_contract.py
python tools/tests/test_da218e_i2c_contract.py
```

Expected: 全部 PASS；分片测试证明前缀不会提前结束，状态 `0..5` 均原样返回。

- [ ] **Step 5: 检查本任务差异**

Run:

```powershell
git diff --check -- include/config.h include/ec800m_at_response.h src/ec800m_at_response.c src/ec800m.c src/hw_init.c Makefile tools/tests/test_ec800m_netreg_transaction.py tools/tests/test_hardware_pin_contract.py
```

Expected: exit 0。不得提交。

---

### Task 2: 配置 v3 掉电安全双鉴权码

**Files:**
- Create: `tools/tests/test_flash_config_v3.py`
- Modify: `include/flash_config.h`
- Modify: `src/flash_config.c`
- Modify: `tools/tests/test_flash_config_migration.py`
- Modify: `tools/tests/test_ext_flash_layout.py`

**Interfaces:**
- Produces fields:
  - `char auth_code[CFG_AUTH_LEN]`：主通道鉴权码，保留字段位置兼容 v1/v2。
  - `char backup_auth_code[CFG_AUTH_LEN]`：追加在 `device_config_t` 尾部的 v3 字段。
- Produces:
  - `bool cfg_store_candidate(const device_config_t *candidate)`：成功时持久化最新 generation 并原子更新 RAM live copy。
  - `bool cfg_set_auth_code(uint8_t channel, const char *code)`：只修改并提交对应通道，长度必须 `< CFG_AUTH_LEN`。

- [ ] **Step 1: 编写真实 NOR 与掉电切点失败测试**

新 harness 用两个 4 KiB 数组模拟配置槽；编程执行 `flash[i] &= input[i]`，擦除填 `0xFF`。为每一次 erase/write 调用提供故障序号，重启通过重新调用 `cfg_init()` 完成恢复。

至少断言：

```c
assert(CFG_VERSION == 3U);
assert(cfg_set_auth_code(EC800M_CH_MAIN, "MAIN-AUTH"));
assert(strcmp(cfg_get()->auth_code, "MAIN-AUTH") == 0);
assert(cfg_set_auth_code(EC800M_CH_BACKUP, "BACK-AUTH"));
assert(strcmp(cfg_get()->backup_auth_code, "BACK-AUTH") == 0);
```

对目标槽擦除、头/数据/CRC 写入、commit marker 写入前后的每个切点循环断电，重启后只能读到旧完整值或新完整值，不能读到混合结构。构造 v1/v2 原始字节，验证 v2 `auth_code` 迁移到主通道、备通道为空。

- [ ] **Step 2: 运行 RED**

Run:

```powershell
python tools/tests/test_flash_config_v3.py
python tools/tests/test_flash_config_migration.py
```

Expected: v3 测试因版本仍为 2、字段/API 不存在失败；现有迁移测试仍应通过，证明 RED 不是基线损坏。

- [ ] **Step 3: 实现 v3 记录格式和选择规则**

v3 槽格式固定为：

```c
typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    uint16_t data_len;
    uint32_t generation;
} slot_v3_hdr_t;

#define CFG_VERSION       3U
#define CFG_COMMIT_MARKER 0x43464733UL
```

槽内容为 `[slot_v3_hdr_t][device_config_t][crc32][commit_marker]`。CRC 覆盖 header 中的 `version/data_len/generation` 和完整数据，不覆盖 magic 与 commit marker。有效 v3 槽必须同时满足 magic、版本、长度、CRC、commit marker。

写入算法：

1. 选择非当前槽，generation=`current+1`（按有符号差处理 wrap）。
2. 擦除目标槽。
3. 写 header、数据和 CRC 并验证。
4. 单独最后写 commit marker，使用 `ext_flash_write_result()`；结果不确定时回读完整槽 reconcile。
5. 只有新槽完整有效后才更新 `s_cfg`、active slot 和 generation。

启动选择两个有效 v3 槽中更新的 generation；没有 v3 时读取 v2/v1，并先在另一槽生成 v3，再处理原槽。禁止先擦除唯一有效旧槽。

- [ ] **Step 4: 运行 GREEN 和存储回归**

Run:

```powershell
python tools/tests/test_flash_config_v3.py
python tools/tests/test_flash_config_migration.py
python tools/tests/test_ext_flash_store_host.py
python tools/tests/test_ext_flash_layout.py
python tools/tests/test_f39_end_to_end.py
```

Expected: 全部 PASS；掉电枚举没有混合配置，v1/v2 均可迁移。

- [ ] **Step 5: 检查结构预算和差异**

在测试中断言 v3 槽总长度 `< FLASH_SECTOR_SIZE`。运行：

```powershell
git diff --check -- include/flash_config.h src/flash_config.c tools/tests/test_flash_config_v3.py tools/tests/test_flash_config_migration.py
```

Expected: exit 0。不得提交。

---

### Task 3: 生成并持久化稳定 JT808-2013 身份

**Files:**
- Modify: `include/terminal_identity.h`
- Modify: `src/terminal_identity.c`
- Modify: `tools/tests/test_terminal_identity.py`
- Modify: `src/main.c`

**Interfaces:**
- Produces:
  - `bool terminal_identity_sync(char pid[12], char phone[13], char terminal_id[8])`
  - `bool terminal_identity_encode_phone(const char pid[12], uint8_t bcd[6])`
- `terminal_identity_sync` 在返回 true 前保证 PID 已经存在于最新有效配置中。

- [ ] **Step 1: 扩展身份 host harness**

将期望从旧“任意 7–15 位 IMEI 可直接取末 7 位”改为已确认规则：

```c
set_identity("", "123456789012345");
assert(terminal_identity_sync(pid, phone, terminal_id));
assert(strcmp(pid, "56789012345") == 0);
assert(strcmp(phone, "056789012345") == 0);
assert(strcmp(terminal_id, "9012345") == 0);
assert(s_store_calls == 1U);

set_identity("12345678901", "987654321098765");
assert(terminal_identity_sync(pid, phone, terminal_id));
assert(strcmp(pid, "12345678901") == 0);
assert(s_store_calls == 0U);
```

覆盖持久化失败：`cfg_store_candidate` 返回 false 时函数返回 false、live config PID 仍为空。覆盖 14 位、16 位、非数字 IMEI 和非空非法 PID 均失败。

- [ ] **Step 2: 运行 RED**

Run:

```powershell
python tools/tests/test_terminal_identity.py
```

Expected: 因新 API 不存在以及旧实现接受短 IMEI而失败。

- [ ] **Step 3: 实现原子身份同步**

核心顺序：

```c
device_config_t candidate = *cfg_get();
/* validate existing PID, or derive exactly 11 digits from exact 15-digit IMEI */
if (candidate.pid[0] == '\0') {
    memcpy(candidate.pid, imei + 4, 11U);
    candidate.pid[11] = '\0';
    if (!cfg_store_candidate(&candidate)) return false;
}
```

然后生成 12 位 phone 和 7 位 terminal ID；所有输出在入口先清零，失败不得留下半成品。`main.c` 不再从未持久化的 IMEI 直接构造终端 ID。

- [ ] **Step 4: 运行 GREEN 和身份消费者回归**

Run:

```powershell
python tools/tests/test_terminal_identity.py
python tools/tests/test_f39_actions.py
python tools/tests/test_f39_end_to_end.py
```

Expected: 全部 PASS；编译使用 `-Wall -Wextra -Werror`。

- [ ] **Step 5: 检查敏感日志**

Run:

```powershell
rg -n "IMEI=%s|ICCID=%s|auth -> %s|PID=%s" src include
```

Expected: 新增链路不打印 PID/鉴权码；删除或脱敏当前启动身份明文日志。随后 `git diff --check` exit 0。

---

### Task 4: 实现可独立测试的单通道 JT808 会话引擎

**Files:**
- Create: `include/jt808_session.h`
- Create: `src/jt808_session.c`
- Create: `tools/tests/test_jt808_session.py`
- Modify: `Makefile`

**Interfaces:**
- Produces:

```c
typedef enum {
    JT808_SESSION_IDLE = 0,
    JT808_SESSION_REGISTERING,
    JT808_SESSION_AUTHENTICATING,
    JT808_SESSION_ONLINE,
    JT808_SESSION_BACKOFF,
} jt808_session_state_t;

typedef enum {
    JT808_ACTION_NONE = 0,
    JT808_ACTION_REGISTER,
    JT808_ACTION_AUTH,
} jt808_session_action_t;

typedef struct {
    uint8_t channel;
    jt808_session_state_t state;
    uint32_t generation;
    uint16_t pending_serial;
    uint32_t sent_ms;
    uint32_t backoff_until_ms;
    uint8_t attempts;
    bool pending_valid;
    bool waiting_first_fix;
} jt808_session_t;

void jt808_session_init(jt808_session_t *session, uint8_t channel);
void jt808_session_sync_link(jt808_session_t *session, bool open,
                             uint32_t generation);
jt808_session_action_t jt808_session_next_action(
    const jt808_session_t *session, bool has_auth, uint32_t now);
void jt808_session_mark_sent(jt808_session_t *session,
                             jt808_session_action_t action,
                             uint16_t serial, uint32_t now);
bool jt808_session_accept_register(const jt808_session_t *session,
                                   uint32_t generation,
                                   uint16_t response_serial);
bool jt808_session_accept_auth(const jt808_session_t *session,
                               uint32_t generation,
                               uint16_t response_serial);
void jt808_session_mark_online(jt808_session_t *session);
void jt808_session_reject_or_timeout(jt808_session_t *session, uint32_t now);
```

- [ ] **Step 1: 写纯状态机失败测试**

用两个真实 `jt808_session_t` 实例覆盖：空鉴权码产生 REGISTER、有鉴权码产生 AUTH；`mark_sent` 后 5 秒内无动作；第 3 次超时进入 60 秒 BACKOFF；主会话断链不改变备会话；generation 变化使旧应答不被接受；成功鉴权只使目标会话 ONLINE。

关键字面量：

```c
assert(jt808_session_next_action(&main, false, 0U) == JT808_ACTION_REGISTER);
jt808_session_mark_sent(&main, JT808_ACTION_REGISTER, 7U, 100U);
assert(!jt808_session_accept_register(&main, 2U, 7U));
assert(jt808_session_accept_register(&main, 1U, 7U));
```

- [ ] **Step 2: 运行 RED**

Run:

```powershell
python tools/tests/test_jt808_session.py
```

Expected: 头文件/实现不存在导致失败。

- [ ] **Step 3: 实现最小纯状态机**

时间比较统一使用 wrap-safe 形式：

```c
static bool deadline_reached(uint32_t now, uint32_t deadline)
{
    return (int32_t)(now - deadline) >= 0;
}
```

`sync_link(false, ...)` 清除待处理事务并回到 IDLE；open 且 generation 改变时同样重置，但保留由上层持久化的鉴权码。第 1–2 次超时回 IDLE 允许下一次动作；第 3 次进入 BACKOFF，截止 `now + 60000U`。

- [ ] **Step 4: 运行 GREEN**

Run:

```powershell
python tools/tests/test_jt808_session.py
```

Expected: PASS，`-Wall -Wextra -Werror` 无输出。

- [ ] **Step 5: 检查差异**

Run `git diff --check` 仅覆盖新模块、测试和 Makefile，Expected exit 0。不得提交。

---

### Task 5: 将 JT808 帧处理改为双会话和逐通道路由

**Files:**
- Create: `tools/tests/test_jt808_dual_session.py`
- Modify: `include/jt808.h`
- Modify: `src/jt808.c`
- Modify: `src/main.c`
- Modify: `tools/tests/test_terminal_identity.py`
- Modify: `tools/tests/test_jt808_registration_tx.py`
- Modify: `tools/tests/test_blind_zone_replay.py`

**Interfaces:**
- Consumes: Task 2 `cfg_set_auth_code`，Task 3 `terminal_identity_sync`，Task 4 会话 API。
- Produces:
  - `bool jt808_channel_online(uint8_t channel)`
  - `uint8_t jt808_online_mask(void)`：bit0=主、bit3=备。
  - `int jt808_send_register_to(uint8_t channel)`
  - `int jt808_send_auth_to(uint8_t channel, const char *code)`
  - `int jt808_send_general_resp_to(uint8_t channel, uint16_t resp_sn, uint16_t resp_id, uint8_t result)`
- 旧 `jt808_is_online()` 保留为“至少一个通道已鉴权”，避免无关调用方大范围改动。

- [ ] **Step 1: 编写双通道帧级 RED harness**

真实编译 `jt808.c`、`jt808_session.c`、`terminal_identity.c`，socket 和 Flash 仅在硬件边界替换为确定性 fake。捕获每个通道发送的完整转义帧，并注入真实带校验的 `0x8100/0x8001`。

必须证明：

1. CH0/CH3 同时 open 且均无鉴权码时各收到一个 `0x0100`。
2. 两个注册流水号分别绑定；CH3 的 `0x8100` 不能推进 CH0。
3. CH0 保存 `MAIN-AUTH`，CH3 保存 `BACK-AUTH`，并分别收到 `0x0102`。
4. `0x8001` 的通道、generation、应答流水号、原消息 ID、结果码任一错误均不上线。
5. CH0 断开只清 CH0；CH3 仍 ONLINE。
6. 平台命令的 `0x0001` 从原通道返回，不广播。
7. 注册体省市字节为 `00 00 00 00`，消息头 BCD 为已确认的 `0 + PID`，终端 ID 为 PID 末 7 位。

- [ ] **Step 2: 运行 RED**

Run:

```powershell
python tools/tests/test_jt808_dual_session.py
```

Expected: 当前只发送 active channel 且只有一套 `s_reg/s_auth_*`，断言失败。

- [ ] **Step 3: 用两个静态会话替换单全局会话**

在 `jt808.c` 使用：

```c
static jt808_session_t s_sessions[2];

static jt808_session_t *session_for_channel(uint8_t channel)
{
    if (channel == TCP_CH_MAIN) return &s_sessions[0];
    if (channel == TCP_CH_BACKUP) return &s_sessions[1];
    return NULL;
}
```

注册、鉴权和通用应答全部调用 `send_frame_channel`。每次 `jt808_process()` 分别读取 `tcp_manager_ch_online()` 和 `tcp_manager_session_generation()`，先同步两个会话，再执行各自 action。

处理 `0x8100`：先验证 body 至少 3 字节；成功时鉴权码长度为 `body_len-3`，必须在 `1..CFG_AUTH_LEN-1`，复制到临时 NUL 结尾缓冲，持久化对应通道后才发送 AUTH。持久化失败保持 REGISTERING/BACKOFF，不使用仅 RAM 鉴权码。

处理 `0x8001`：验证 5 字节应答体、`reply_msg_id==0x0102`、结果 0，并通过对应 session 的 generation/serial 校验后 `mark_online`。拒绝和超时走该通道退避；连续鉴权耗尽调用 `cfg_set_auth_code(channel, "")`。

- [ ] **Step 4: 调整主循环顺序**

把：

```c
jt808_process();
tcp_manager_process();
```

改为：

```c
tcp_manager_process();
jt808_process();
```

使本轮新建/断开的 TCP generation 在 JT808 动作前可见。

- [ ] **Step 5: 运行 GREEN 与协议回归**

Run:

```powershell
python tools/tests/test_jt808_dual_session.py
python tools/tests/test_terminal_identity.py
python tools/tests/test_jt808_registration_tx.py
python tools/tests/test_blind_zone_replay.py
python tools/tests/test_ec800m_urc_demux.py
python tools/tests/test_ec800m_qisend.py
```

Expected: 全部 PASS；日志无鉴权码明文。

- [ ] **Step 6: 检查差异和静态 RAM**

Run `git diff --check` 覆盖本任务文件。记录 `sizeof(jt808_session_t) * 2` 的 host 输出，目标应小于 128 字节总计；若超过，压缩布尔/枚举字段而不改变行为。

---

### Task 6: 实现可信首次定位和双通道周期上报

**Files:**
- Create: `tools/tests/test_jt808_first_location.py`
- Modify: `src/jt808.c`
- Modify: `include/jt808.h`
- Modify: `tools/tests/test_blind_zone_store.py`（仅当现有夹具接口变化）
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 5 `jt808_channel_online` 和两个 session 的 `waiting_first_fix`。
- Produces:
  - `bool jt808_location_snapshot_valid(const gps_data_t *gps, uint32_t now)`，可放在 `jt808.c` 内部并通过真实公开发送行为测试。
  - `int jt808_send_location_to(uint8_t channel, const gps_data_t *snapshot)`，只接受已鉴权通道和不可变快照。

- [ ] **Step 1: 编写首次定位和路由 RED harness**

注入可变 `gps_data_t` 和两个在线状态，手工解码发送帧，覆盖：

```c
gps.valid = false;
jt808_process();
assert(location_count[MAIN] == 0U && location_count[BACKUP] == 0U);

gps.valid = true;
gps.fix_quality = 1U;
gps.last_update_ms = g_tick_ms;
gps.year = 2026U; gps.month = 8U; gps.day = 31U;
gps.hour = 2U; gps.minute = 3U; gps.second = 4U;
jt808_process();
assert(location_count[MAIN] == 1U && location_count[BACKUP] == 1U);
```

再覆盖：只有 CH3 在线只发 CH3；`last_update_ms` 超过 5000 ms 不发；year/month/day 为 0 不发；一个通道发送失败不阻止另一通道；同一次有效边沿不会在下一主循环重复首报。

帧字段使用手工值校验：经纬度乘 `1e6`、速度乘 `10`、方向/海拔大端、北京时间 UTC+8 的跨月/闰年进位和 BCD 时间。

- [ ] **Step 2: 运行 RED**

Run:

```powershell
python tools/tests/test_jt808_first_location.py
```

Expected: 当前 `process_location_timer()` 在鉴权前运行、允许冻结坐标且只向单通道发送，断言失败。

- [ ] **Step 3: 实现不可变定位快照和逐通道发送**

有效条件必须同时满足：

```c
gps != NULL && gps->valid && gps->fix_quality > 0U &&
(uint32_t)(now - gps->last_update_ms) <= 5000U &&
gps->year >= 2000U && gps->month >= 1U && gps->month <= 12U &&
gps->day >= 1U && gps->day <= 31U &&
gps->hour <= 23U && gps->minute <= 59U && gps->second <= 59U
```

首报只清除成功通道的 `waiting_first_fix`。周期到期时先复制 `gps_data_t snapshot = *gps_get_data()`，基于同一 snapshot 构建 body，再分别向所有 ONLINE 通道发送。一个成功、一个失败时返回“至少一条成功”，不把该点追加盲区；全失败/全离线才沿用现有盲区追加事务。

移除实时 `0x0200` 对 `s_frozen_pos` 的替代；冻结位置如仍用于其他静止算法，不得设置 GPS fixed 或进入首次实时定位路径。

- [ ] **Step 4: 运行 GREEN 和定位/盲区回归**

Run:

```powershell
python tools/tests/test_jt808_first_location.py
python tools/tests/test_blind_zone_store.py
python tools/tests/test_blind_zone_replay.py
python tools/tests/test_gps_tx_bounded.py
```

Expected: 全部 PASS；无有效日期时无 `0x0200`。

- [ ] **Step 5: 更新 README**

明确写入：JT/T 808-2013；PID/消息头/终端 ID 规则；双服务器独立鉴权；首次有效定位策略；EC800M、双 TCP 和 GNSS 仍需要实机/HIL。

- [ ] **Step 6: 检查差异**

Run `git diff --check` 覆盖本任务文件，Expected exit 0。不得提交。

---

### Task 7: 全量验证、资源门禁和交付检查

**Files:**
- Modify only if verification exposes a task-scope defect; every such fix must start a fresh RED→GREEN cycle in the owning task test.

- [ ] **Step 1: 运行所有新增定向测试**

```powershell
python tools/tests/test_ec800m_netreg_transaction.py
python tools/tests/test_flash_config_v3.py
python tools/tests/test_terminal_identity.py
python tools/tests/test_jt808_session.py
python tools/tests/test_jt808_dual_session.py
python tools/tests/test_jt808_first_location.py
```

Expected: 全部 PASS，无 SKIP（要求可用 host C 编译器）。

- [ ] **Step 2: 运行相关现有回归**

```powershell
python tools/tests/test_feature_guards.py
python tools/tests/test_hardware_pin_contract.py
python tools/tests/test_i2c_bus_recovery_contract.py
python tools/tests/test_da218e_i2c_contract.py
python tools/tests/test_ec800m_netreg_freshness.py
python tools/tests/test_ec800m_health_observability.py
python tools/tests/test_ec800m_urc_demux.py
python tools/tests/test_ec800m_qisend.py
python tools/tests/test_flash_config_migration.py
python tools/tests/test_blind_zone_store.py
python tools/tests/test_blind_zone_replay.py
python tools/tests/test_ext_flash_store_host.py
python tools/tests/test_ext_flash_layout.py
```

Expected: 全部 PASS。报告第一个真实失败，不用后续成功掩盖。

- [ ] **Step 3: 构建普通固件**

```powershell
make all
```

Expected: `build/a300_firmware.hex` 生成，无新增编译警告；记录 Flash/RAM usage。构建产物仅作验证，不覆盖 `firmware/` 或既有发布归档。

- [ ] **Step 4: 运行发布与 RAM 门禁**

```powershell
make release-guard
make ram-guard
```

Expected: 两者 PASS；若 RAM guard 失败，优先缩小会话/局部帧缓冲，不关闭安全检查或 LTO 证据。

- [ ] **Step 5: 构建硬件调试配置**

```powershell
make all EXTRA_CFLAGS=-DA300_HARDWARE_BRINGUP
```

Expected: `build-hardware-bringup/a300_firmware.hex` 生成，无新增警告；不把该调试构建称为发布固件。

- [ ] **Step 6: 最终差异审查**

```powershell
git diff --check
git status --short
git diff -- include/config.h include/ec800m_at_response.h include/flash_config.h include/terminal_identity.h include/jt808_session.h include/jt808.h src/ec800m_at_response.c src/ec800m.c src/flash_config.c src/terminal_identity.c src/jt808_session.c src/jt808.c src/main.c Makefile README.md tools/tests
```

确认没有完整 IMEI/ICCID/PID/鉴权码、临时调试绕过、无限重试、无关格式化或参考 N32G452 工程改动。

- [ ] **Step 7: 交付实机/HIL验证清单**

明确标记“需要实机/HIL验证”：

1. AF6 后 I2C2 SCL/SDA 高、BUSY 清零、DA218E CHIPID `0x13`。
2. EC800M `CEREG/CGREG` 真实状态达到 1/5、PDP READY。
3. 主/备 TCP 各自收到 `0x0100/0x0102`，平台应答绑定正确。
4. 重启后两个通道分别使用持久化鉴权码直鉴权。
5. 首次 GNSS 有效定位和周期 `0x0200` 同时到达两个在线平台。
6. 单路断网、PDP deact、错流水号、旧连接应答和平台拒绝均不影响另一通道或形成重启风暴。

不得烧录、部署或发送真实控制命令，除非用户另行明确授权。
