# 毫米量化与数学/日志瘦身合并编译

2026-09-16：仅隔离实验，默认源码、构建配置、版本和既有烧录包未改。

| 配置 | ELF 文件/B | HEX 文件/B | BIN / App 占用/B | App 剩余/B |
|---|---:|---:|---:|---:|
| 默认基线 | 161208 | 294158 | 104560 | 1936 |
| 有界 double + 4 条普通日志裁剪 | 150868 | 274689 | 97636 | 8860 |
| 上述方案 + 毫米量化及无效输入保护 | 151004 | 275033 | 97756 | 8740 |

App 分区 106496 B。新方案增加 120 B，较默认节省 6804 B。
ELF/HEX 是容器文件大小，不能直接当作 Flash 占用。
历史实验与本次记录的输入哈希对比：仅实验生成器变化，其余共同记录输入相同。

实现：`firmware_size_trial.py --quantize-mm` 在数学候选上应用毫米规则；
`replay_mileage_size_trial.py --quantize-mm` 回放真实 C 更新函数；
新增 `tools/tests/test_mileage_quantization.py` 检查真实更新函数的边界、重复点和无效输入。
源文件覆盖仅生成在 build 目录内，未安装为默认实现。

规则依照量化草案：四舍五入到毫米，漂移距离小于阈值才拒绝，
500 < mm < 1000000 才调用累加，按 mm/1000 截断到米，不累计余数。
先验证坐标范围，非有限/负距离不推进基准点，有限大距离钳制至 8192 m。
501..999 mm 保留加零调用；通过漂移过滤后仍推进基准点。

执行命令与结果：

```text
python tools/tests/test_mileage_quantization.py --baseline
  预期失败：旧规则不满足新边界断言（RED）。
python tools/tests/test_mileage_quantization.py
  PASS（GREEN）。
python tools/tests/test_size_trial.py
  4 tests PASS。
python tools/experiments/replay_mileage_size_trial.py --math bounded --quantize-mm --output build/mileage-quantized-replay-20260916
  exit 0；25128 点对，12000 连续样本，两个真实 C 持久化回归 PASS。
python tools/experiments/firmware_size_trial.py --math bounded --quantize-mm --cases combined --output build/mileage-quantized-combined-20260916
  ARM build exit 0，无 warning；Flash、release-guard、信任锚、libc、必要栈帧检查通过。
  内部 release-gate exit 2：完整栈/堆/异常证据不足。
git -c core.safecrlf=false diff --check
  exit 0。
```

真实 C 回放与旧规则相比有 985 点对决策变化；6 条连续轨迹终值分别变化
0、0、0、+1、+2、+1 米（每条约 69–71 km）。3830 行持续状态不同，
包含累计差异传播，不能解释为 3830 次独立错误。此前 Python 规则评估
不是本次 C 回放的验收证据，以本次真实 C 结果为准，不声明旧行为等价。

RAM：static=17892 B，已知主调用链帧=2536 B，堆/IRQ/未知项前剩余
4148 B，仅高于 4096 B 必要间隔 52 B；完整安全边界未证明。

产物：`build/mileage-quantized-combined-20260916/combined/a300_firmware.{elf,hex,bin}`。
保留 V3.051 实验身份，非新发布或 Combined 烧录包，release_approved=false。
需要实机/HIL 验证 ARM 数学边界、实际行车里程、静止漂移、重启持久化和 RAM 水位。
8740 B 不是未来 AGNSS/产测/0x8103 完成对接后的剩余预算。
