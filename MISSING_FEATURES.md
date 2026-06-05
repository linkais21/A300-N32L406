# 不可独立实现功能记录

**项目**: A300-T9 / T663B GPS 追踪器固件重构  
**日期**: 2026-06-04  
**状态**: 本文档记录因资料不足无法独立实现的功能，供同事配合完成。

---

## 1. AGPS 辅助定位

### 功能描述
冷启动加速。向 AGPS 服务器请求星历/历书数据，注入 TAU804M-N2B0 GPS 模组，
将冷启动首次定位时间（TTFF）从 2–3 分钟缩短至 15–30 秒。

### 反编译中的证据
```
s_AGPS_ON / s_AGPS_OFF   — 功能开关
s_AGPSUSUR               — 服务器标识符
s_Read_AGPS>_d__0_2x     — 数据读取模式
s_AGPS Not connected      — 连接失败提示
```

### 缺失的关键信息

**（A）AGPS 服务器协议**  
原固件连接的服务器疑似为移远官方 AGPS 服务（`agps.qxwz.com` 或类似），
通信协议（HTTP? 私有 TCP?）、请求格式、鉴权方式均未在反编译中找到明文。

**（B）数据注入格式**  
TAU804M-N2B0 使用 CASIC 芯片（北斗双频）。CASIC AGPS 数据注入命令格式
（二进制帧结构）不在公开 NMEA 规范中，需要华大（U-blox？）提供的
《TAU804M 应用指导》或《CASIC AGPS 协议说明》。

### 需要同事提供

| 资料 | 负责人 | 优先级 |
|------|--------|--------|
| TAU804M-N2B0 AGPS 应用指导（华大官方文档） | — | 高 |
| AGPS 服务器地址 + 鉴权方式（可从原设备抓包获取） | — | 高 |
| CASIC AGPS 二进制注入命令格式 | — | 高 |

### 参考实现接口
代码框架已预留（`include/flash_config.h` 中的 `agps_ip/agps_port/agps_en`）。
一旦获得协议文档，只需实现 `src/agps.c`：
```c
void agps_start(void);           // 连接服务器，下载星历
void agps_inject_to_gps(void);   // 通过 USART2 注入 TAU804M
```

---

## 2. NTRIP RTK 差分定位

### 功能描述
通过 NTRIP 协议从差分服务器（`rtk.ntrip.qxwz.com`）接收 RTCM 差分数据，
发送给 TAU804M GPS 模组，实现厘米级精度定位（RTK Fix）。

### 反编译中的证据
```
rtk_ntrip_qxwz_com       — 服务器域名
User-Agent: NTRIP         — HTTP 头标识
s_RTKINFO / s_RTKSW       — RTK 配置参数
```

### 已知可实现部分（协议公开）
NTRIP 协议本身是公开的 RTCM SC-104 标准（HTTP/1.0 变体）：
- 客户端请求：`GET /mountpoint HTTP/1.0\r\nAuthorization: Basic base64(user:pass)\r\n`
- 服务器响应 RTCM3 数据流
- 客户端每隔 N 秒上传 GGA 定位报告（服务器据此分配最近基站）

### 缺失的关键信息

**（A）RTCM 数据注入格式**  
TAU804M-N2B0 接受 RTCM3 数据流通过 UART 注入，但具体的注入方式
（直接透传？还是需要 CASIC 特定命令封装？）需要华大提供文档确认。

如果 TAU804M 支持直接 RTCM3 透传（大多数 CASIC 双频模组支持），
则注入方式为直接将收到的 RTCM 字节转发到 USART2（GPS UART）。

**（B）NTRIP 账号信息**  
千寻 `qxwz.com` 服务需要账号（用户名+密码+挂载点），原设备的账号不可见。
实际部署需要：
- 用于测试的 NTRIP 账号（千寻/科石/自建基站均可）
- 确认 TAU804M RTCM3 注入是否需要特殊使能命令

### 需要同事提供

| 资料 | 负责人 | 优先级 |
|------|--------|--------|
| TAU804M RTCM3 注入方式确认（直接透传 or 命令封装） | — | 高 |
| 可用于测试的 NTRIP 账号（或自建基站） | — | 中 |
| CASIC 差分定位使能命令（如有） | — | 中 |

### 参考实现接口
代码框架已预留（`flash_config.h` 中 `rtk_ip/rtk_port/rtk_user/rtk_pass/rtk_mount`）。
NTRIP 客户端实现约 200 行，主体逻辑为：
```c
void ntrip_start(void);    // 连接 TCP CH4，发送 HTTP 请求
void ntrip_process(void);  // 接收 RTCM 数据→转发到 GPS UART
                           // 每30s上传一次 GGA 定位句
```
**RTCM 注入格式一旦确认，2小时内可完成实现。**

---

## 总结

| 功能 | 阻塞原因 | 解决方案 | 工作量（一旦有资料） |
|------|----------|----------|---------------------|
| AGPS | CASIC 注入协议 + 服务器协议未知 | 获取华大 TAU804M AGPS 文档 | 1天 |
| NTRIP | RTCM 注入方式待确认 | 确认 TAU804M 支持直接透传 | 半天 |

两项功能的**代码框架均已就绪**，阻塞点是纯协议文档问题，不涉及硬件改动。

"D:\A700open\A300\pcb\A300-T9通讯板-1.png"
