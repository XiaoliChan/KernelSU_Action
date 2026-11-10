# OnePlus 9R 实机启动故障定位

## 已确认事实

用户报告 SukiSU-Ultra 内核刷入后停在一加 Logo，恢复已备份的 `boot_a` 后可以正常开机。Recovery 可以启动，但 pstore 为空，`/proc/last_kmsg` 不存在。当前没有失败内核的 panic 栈，不能断言某个具体补丁就是根因。

已对用户实际刷入的 ZIP、可开机备份和失败 boot 进行离线检查，原始文件未修改：

- ZIP SHA256 与发布的 `-devicefix.zip` 一致。
- 失败 boot 中的内核与 ZIP 内核逐字节相同。
- DTB、启动参数、头部版本、页大小和加载地址相同。
- ramdisk 的差异符合卸载 Magisk：失败镜像的 `init` 与备份 `.backup/init.xz` 解压结果相同，其余共同文件内容、权限和属主相同。
- 使用原内核、卸载后的 ramdisk 和原 DTB 重建的纯净镜像，匹配原 AVB 描述符记录的 payload 大小及 SHA256；AOSP avbtool 验证通过。这里的 AVB 算法是 NONE，此结论是哈希完整性检查，不是签名认证。
- 在这个纯净镜像里仅替换为 ZIP 的内核，更新必要的尺寸、header ID 和 footer 偏移，能够逐字节复现完整失败 boot：**差异字节数为 0**。

因此，没有发现安装器对 ramdisk、DTB、头部造成额外修改或损坏。下一步重点排查内核构建配置与 KernelSU/SUSFS 运行时集成，不能把“APK 不兼容”或“Orange State”当作当前已证实的原因。

## 可开机内核与失败内核的实际差异

| 项目 | 可开机内核 | 失败内核 |
| --- | --- | --- |
| Clang | r596125 / 22.0.2 | r547379 / 20.0.0 |
| RELR | 启用 | 未启用 |
| LOCALVERSION | `-perf` | `-OnePlus9R` |
| KPROBES | 启用 | 禁用 |
| KernelSU / SUSFS | 无 | 启用 |

这些是从两个内核的嵌入 `.config` 中提取的事实，不是已确认的启动故障因果。不能简单换个 clang 就宣称修复，也不能在缺少设备模块及加载日志的情况下断言 vermagic 是根因。

## 对照实验

新增 `Build OnePlus 9R (Stock control)` 手动工作流，专用于建立可复现的构建基线：

1. 固定内核源码到 `078365e5318de0a30a41f9707070b610bcd20f13`。
2. 使用可开机内核的原始配置快照和 Clang r596125，全 LLVM 工具链。工具链固定到 AOSP 预编译提交 `9b144befdfd93b90e02c663504fb9f4b95f9faf8`，对应原机 Android build `15071444`；不使用已被覆盖为 build `15682573` 的移动分支目录。
3. 不安装 KernelSU，不应用任何 SUSFS、manual-hook、path_umount 或 hide_stuff 补丁。
4. 生成配置后逐项比对；有差异就停止，不把偏离的配置当作有效对照组。
5. 只上传诊断 Artifacts，权限仅 `contents: read`；没有 Release 发布入口。

对照组编译成功仍不代表实机验证成功。先验证基线能启动，再分阶段引入 root 与 SUSFS；不要继续轮流刷当前三个功能齐全的版本来猜原因。

## 对照组实机结果与最小 SukiSU 阶段

对照构建 `42813347213` 已经在用户手机通过一次授权的 `fastboot boot` 临时启动。ADB 的 `sys.boot_completed=1`，且 `/proc/version` 显示此次构建身份与时间，而不是原系统的构建身份。本次没有执行 `fastboot flash`。

新增 `Build OnePlus 9R (SukiSU minimal)` 作为第二阶段，仍不发布 Release：

- 同一源码、Clang build 15071444、原始配置；使用内核自带 `--save-scmversion` 在集成前保存干净源码后缀，保持原 `-perf` kernel release。
- SukiSU 固定到 `1cfa57340590971cba7521ed536da8ebbedc5f0a`。配置检查只接受新增 `CONFIG_KSU=y`；显式关闭默认开启的 SUSFS 和 ADB-root 特性，并关闭 KPM/debug。原 KPROBES、RELR、CC_WERROR 等不能静默改变。
- 该提交没有 `CONFIG_KSU_MANUAL_HOOK` 选项，不能靠写一个不存在的 Kconfig 符号证明 hook 已接入。此阶段直接应用版本固定的手动 hook 补丁。
- 非 SUSFS 分支通过自己的 LSM hook 处理 UID 变化，不定义 SUSFS 分支的 `ksu_handle_setresuid`，因此最小补丁不插入那个调用；同时接入上游已有的 fstat 长度修正入口，与 init.rc read hook 配对。
- 保留必要的 4.19 兼容：`path_umount` 回移、未使用 static-call API 的头文件兼容、已存在的 clocksource/access_ok 适配。没有复制或编译 SUSFS 文件。
- 上游非 SUSFS preinit 位于 unity build 的 `preinit/common`，独立 preinit 对象只应为 SUSFS 分支构建，最小专用补丁限制该对象选择，避免两种实现同时链接。

这里的“最小”指最小诊断配置，不表示裁掉上游所有不可配置的内部功能。该候选是否能启动及是否能正常授权 root，仍需单独的设备验证；不能用对照组成功代替 root 版验证。

第一轮最小 SukiSU 构建 `42823311868` 通过了配置校验，但编译失败：reboot hook 在局部变量声明前执行语句；上游非 SUSFS 分支存在 `KSU_NO_PREINIT` 重定义、未加条件保护的 SUSFS 调用和旧内核分支的未使用变量。针对这些错误修正源代码，不关闭参考配置的 `CONFIG_CC_WERROR`。

两个诊断工作流现启用 3 GB ccache，明确统一缓存路径、以编译器内容校验身份，并按系统/架构/固定工具链分组。每轮使用唯一保存键及共同恢复前缀，编译报错也保存已完成的缓存，并输出本轮命中统计。首次为冷缓存；缓存不加速链接，也不会跳过配置或产物检查。
