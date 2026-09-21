# A300-406 V3.065 OTA 成功上报候选包

OTA 上传文件：`A300-406-OTA-V3065.bin`，deviceModel=A300-406，versionCode=3065。
升级后的 ACTIVE 版本联网后上报 success；断网/响应丢失保留记录并有限次补报。
静止锁点用户已确认 PASS，本版保留。

App/Boot 编译及相关自动测试通过，但完整 RAM 发布门禁未通过，详见 CHANGELOG.md。
本包为 HIL 候选，未实机验证、未上传、未部署，不代表量产发布批准。
平台令牌超过 48 小时不能补报；旧版 compact URL 记录可恢复令牌。
SWD-Combined 包含首次启动工厂初始化记录；现有设备保留配置升级请使用 OTA 文件。
SHA256SUMS.txt 包含本目录文件校验值。validation 保留命令、结果和源码哈希。
