# A300_406 构建工具链

Windows 构建使用 ARM GNU Toolchain 14.3.rel1 和 GNU Make 4.4.1。
将 ARM GCC 的 bin 目录映射到仓库内 `.toolchain/bin`，或通过 `TOOLCHAIN_DIR` 指定安装位置。GNU Make 需加入 PATH。

在 `A300-first` 仓库目录的 PowerShell 中构建：

```powershell
make all
make release-guard
make ram-guard
```

默认 `DEBUG_FLAGS=-g0`。需要源码调试信息时使用 `make -B DEBUG_FLAGS=-g3 all` 强制重建；调试段影响 ELF 大小，不直接计入烧录 HEX/BIN。

当前发布输入是 N32L406 固件；历史 N32G452 固件不得混入发布输入。`Makefile` 是主构建依据，旧 `build_all.ps1` 不能作为唯一发布依据。

## 发布版本规则

以 `release_identity.json` 和 README 的冻结发布契约为准：保留 `T360-A300_406_20260823000000` 标识，只递增 `V3.xxx` 修订号。构建时间、FOTA 版本和发布清单需保持一致，并运行发布身份检查。

旧说明要求替换固定时间标识，与当前冻结契约冲突，已在此纠正。本次仅整理构建说明，不生成新发布包或修改发布身份。
