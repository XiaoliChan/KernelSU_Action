# 一加 9：blu_spark 与 LineageOS 内核源码对比

核对日期：2026-11-11。按用户要求，在 9R 的 ADB-root + KPM + SUSFS 和官方管理器验证通过后进行。**只读研究，没有把 SM8350 的补丁或配置移植到手机。**

## 比较对象与边界

| 项目 | blu_spark | LineageOS |
| --- | --- | --- |
| 仓库 | `engstk/op9` | `LineageOS/android_kernel_oneplus_sm8350` |
| 分支 | `blu_spark-17-custom` | `lineage-24.0` |
| 固定提交 | `2a97f7d42aaf1848cc528d0a67e09d39f0218f6d` | `1d4b7dfb75108a66e7312af8b572bd2776c1b1d5` |
| Makefile 版本 | **5.4.302** | **5.4.302** |
| 平台 | OnePlus 9/Pro、SM8350/lahaina | SM8350/lahaina |

来源：[blu_spark Makefile](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/Makefile)、[LineageOS Makefile](https://github.com/LineageOS/android_kernel_oneplus_sm8350/blob/1d4b7dfb75108a66e7312af8b572bd2776c1b1d5/Makefile)。结论只针对这两个快照，不能扩展为所有历史 Release/OOS 分支。

方法：全树路径级差异、配置声明比较、关键实现抽查；**没有编译这两个 OP9 内核，没有 OP9 性能/功耗实测，也没有逐行审计所有差异**。以 LineageOS → blu_spark 方向、不检测重命名，Git 给出 319 个变化路径：217 修改、93 新增、9 删除。不能把它理解为 319 项功能优化：例如 `drivers/power/oplus/adapter_ic/oplus_stm.c` 的差异完全是 CRLF → LF，584 个换行归一化后字节相同。

## 真正有意义的区别

### 1. 调度框架相同，input boost 有局部行为调整

双方 `lahaina-qgki_defconfig` 都声明 WALT、UCLAMP、PREEMPT、Clang LTO、CFI；这些不是 blu_spark 独占功能。两个快照的 `kernel/sched` 树差异集中在 `walt/cpu-boost.c`：

- `input_boost_ms=0` 时直接跳过 boost 工作；
- 输入触发最小间隔由固定 150 ms 改为 `input_boost_ms` 对应时长。

这可能改变触控响应与耗电的取舍，不能从源码直接推出“更快且更省电”。[boost 实现](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/kernel/sched/walt/cpu-boost.c)、[LineageOS 配置](https://github.com/LineageOS/android_kernel_oneplus_sm8350/blob/1d4b7dfb75108a66e7312af8b572bd2776c1b1d5/arch/arm64/configs/vendor/lahaina-qgki_defconfig)。

### 2. ZRAM 默认压缩算法改为 LZ4

LineageOS 源码默认 `lzo-rle`，blu_spark 改为 `lz4`，对应 Kconfig 选择 CRYPTO_LZ4。只是内核默认值，ROM 初始化仍可能覆盖；不能等同于实机一定运行 LZ4。[zram_drv.c](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/drivers/block/zram/zram_drv.c)、[Kconfig](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/drivers/block/zram/Kconfig)。

### 3. 多一些 TCP 算法，但默认仍是 cubic

`blu_spark_defconfig` 开启高级 TCP 拥塞控制及 BBR/HTCP/Westwood；`CONFIG_DEFAULT_TCP_CONG` 仍是 `cubic`。因此“支持 BBR”不等于“默认开启 BBR”，也不能推导所有 App 网络更快。[blu_spark_defconfig](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/arch/arm64/configs/blu_spark_defconfig)。

### 4. 增加显示、振动和 USB 充电可调项

| 项目 | 当前实现 |
| --- | --- |
| 背光 | 新增 `backlight_min`、`backlight_scale`、`backlight_max` 参数；部分面板最大值改用参数值 |
| 振动 | AW8697 新增 level 控制，按 `level * gain / 3` 缩放，默认 level=3 |
| USB 充电 | 新增 `force_fast_charge`，默认关闭；在普通 USB 分支可使用 `ffc_val`，初值 900 mA |
| workqueue | `power_efficient` 参数权限从 0444 改成 0644，让 root 可以修改；不是替换 workqueue 算法 |

来源：[显示](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/techpack/display/msm/dsi/dsi_display.c)、[振动](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/drivers/misc/aw8697_haptic/aw8697.c)、[充电调用点](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/drivers/power/oplus_chg/oplus_charger.c)、[workqueue](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/kernel/workqueue.c)。USB 普通充电电流调整不是 Warp/Dash 协议升级。

### 5. 当前分支还集成 Root 与 SUSFS，不能只把它看成性能内核

当前 blu_spark 快照有 `drivers/kernelsu`，编译对象包含 ADB-root、SELinux hide；配置开启 KSU、kprobes hook、SUSFS。`include/linux/susfs.h` 标记 **v2.3.0**。这是源码现状，不是对所有 blu_spark 发行版的泛化。

该树的 Kconfig/源码文件列表没有我们使用的 KPM bridge 配置和实现，不能当成已经包含我们这套 SukiSU-Ultra + KPM。9R 当前是不同的固定 SukiSU 4.3.0-r2 基线及 **SUSFS v1.5.9-v2compat**，不能直接混用其 v2.3.0 头文件或整个 Root 驱动目录。[Root Kconfig](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/drivers/kernelsu/Kconfig)、[Kbuild](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/drivers/kernelsu/Kbuild)、[SUSFS 版本](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/include/linux/susfs.h)。

### 6. 构建配置更激进，但不能把“关闭告警”当作优化

`blu_spark_defconfig` 关闭 CC_WERROR，修改 localversion/自动 SCM 后缀；若干音频 Kbuild 也去掉 `-Wall/-Werror` 等检查。`op9_defconfig` 则保留 CC_WERROR。必须说明实际选择哪个 profile，不能只看仓库名称判断配置。

检查到的移植前问题：

- 当前顶层 Makefile 的 `-std=gnu89` 行没有续行符；下面新增的 `-mcpu=cortex-a55` 等行不属于该 CFLAGS 赋值。未经实际构建日志确认，不能声称这些编译优化已经生效。
- `dsi_display.c` 的背光缩放除数为 `min(max(0, backlight_scale), 2047)`，允许除数为 0，需补边界检查。
- `fastchg.c` 的 sysfs 创建失败路径重复调用 `kobject_put`，需要先修正引用释放。

这些是抽查发现，不是完整审计，更没有在手机上触发这些路径。[Makefile](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/Makefile#L499-L509)、[fastchg.c](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/drivers/misc/fastchg.c)、[音频 Kbuild](https://github.com/engstk/op9/blob/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d/techpack/audio/asoc/Kbuild)。

## 对你的 9R，哪些值得参考？

9R 是我们实际验证的 **SM8250/4.19.325**，不是 OP9 的 SM8350/5.4.302。继续保留已经跑通的 LineageOS 原配置、工具链、vermagic 和三项组合，不要替换成 OP9 内核。

当前 9R 只读观察（不是对所有 LineageOS ROM 默认值的断言）：

```text
zram0: lzo [lzo-rle] lz4 zstd
policy0 / policy4 / policy7 governor: schedutil
TCP current: cubic; available: reno cubic
workqueue power_efficient: N
```

建议顺序：

1. **先做有指标的配置实验**：9R 已有 LZ4 支持，可以另行安排 lzo-rle/LZ4 对照；记录压缩率、CPU 占用、卡顿和续航，不必先搬 OP9 源码。本次没有切换压缩算法。
2. **再评估小而独立的代码差异**：input boost 边界/间隔、必要的 TCP 算法、workqueue 参数可调性；先核对 4.19 实现与用户空间 Power HAL，再逐项对照测试。
3. **不要直接搬硬件参数**：面板背光、触觉、充电、DTS、GPU/电压/温控相关内容必须按 9R 的硬件与驱动重新验证。
4. **SUSFS v2.3 是后续移植研究，不是复制目录**：5.4 与 4.19 的 VFS、LSM、task flags、用户态 ABI 都要适配。当前 v1.5.9-v2compat 的限制保留明示。

结论：blu_spark 值得参考的是具体可调项和小补丁；**没有性能实测支持“整棵换过去一定更好”**。对你的 9R，稳妥路线仍是已验证的 LineageOS 基线加选择性回移。
