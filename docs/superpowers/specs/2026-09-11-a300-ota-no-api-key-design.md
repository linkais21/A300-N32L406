# A300 OTA 无 API Key 契约对齐设计

## 目标

让 A300_406 在 `FKEY,CONFIGURED=0` 时仍按原始 A300 契约主动检查并下载 OTA，同时让当前 Spring 平台使用检查响应中的短期任务 token 完成下载授权和进度审计。

## 已确认事实

- N32G452 原始 `fota.c` 的检查和下载 GET 不发送 `X-Device-Key`。
- 原始设备只在进度上报 POST 中发送 `X-OTA-Token`。
- 当前 N32L406 `begin_check()` 和 `send_request()` 把空 `device_api_key` 作为硬门禁，导致设备不发送检查请求。
- 当前平台的 `DeviceApiKeyFilter` 拦截所有 `/api/device/**`，而设备没有可配置的 API Key。

## 方案

### 固件

- 删除 `key_valid()` 对 `begin_check()`、`fota_start_request()` 和 HTTP GET 的依赖。
- GET 请求只保留 Host、可选 Range/If-Range、Connection 头。
- 检查响应中的 `downloadToken` 仅保存在本次运行的 RAM 中，用于下载 URL 和下载完成状态上报；不修改 140 字节 Bootloader authorization、BCR、marker 或配置 Flash 格式。
- 固件验证并提交 authorization/BCR 后，通过 `POST /api/device/updates/progress` 携带 `X-OTA-Token` 尽力上报 `downloaded`。上报成功或 15 秒窗口到期后均继续重启，网络上报不得阻塞升级。
- 保留型号、版本、包长度、SHA-256、ECDSA、Range、断点续传、BCR 和回滚校验。

### 平台

- 设备检查和下载路径绕过全局 `DeviceApiKeyFilter`。
- `checkForUpdate` 返回的稳定 URL 附带独立随机的 96-bit token；`ota_tasks.download_token` 保存该 token，不复用可从 URL 路径推导的任务 ID。
- `download_token` 使用唯一索引，保证 token 查询有界且不会因重复值选中错误任务。
- 下载接口从 URL 查询参数读取 token，并要求 token 与任务 ID、设备任务状态匹配；无 token、错误 token、已完成/取消任务返回拒绝。
- 管理端任务响应不返回 `downloadToken` 或带 token 的 `downloadUrl`；凭据只在设备检查响应中下发。
- `downloaded`、`install_started` 和 `success` 状态必须同时上报完整字节数与 100% 进度。
- 新增设备进度接口，要求 `X-OTA-Token` 与任务匹配，校验状态、版本和字节数后写入任务状态/下载偏移及升级日志。
- 管理端鉴权、设备白名单、发布/分配逻辑保持不变。

## 数据流

```text
设备启动
  -> GET /api/device/updates/check?deviceId&deviceModel&currentVersionCode
  <- downloadUrl=.../download?token=<random-token>, downloadToken=<random-token>
  -> GET .../download?token=<random-token> [Range 可选]
  -> POST /api/device/updates/progress [X-OTA-Token: <random-token>]
```

## 错误处理与安全边界

- 没有升级任务仍返回 `{"updateAvailable":false}`。
- token 缺失、格式错误、任务不匹配或任务已终结时，下载/进度接口拒绝请求，不泄露固件内容。
- 固件在写入 Pending/BCR 前继续验证包头、长度、CRC、SHA-256 和签名。
- token 不写入调试日志或 Flash；checkpoint 只保存移除 token 查询参数后的 URL 标识，Flash 中旧 `device_api_key` 只保留布局兼容。

## 验收

- 固件静态契约测试证明空 Key 不阻止检查，GET 不含 `X-Device-Key`，保留 `X-OTA-Token`。
- 平台测试证明无 API Key 的检查可领取任务，错误/缺失 token 无法下载或上报，正确 token 支持 Range。
- 运行固件定向 host tests、固件构建/release guard，以及平台 Maven 测试（环境可用时）。
- 串口设备重启后需实机/HIL 验证出现 OTA 检查请求和下载流量。
