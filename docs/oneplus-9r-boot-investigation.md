# OnePlus 9R 实机启动故障定位

## 已确认事实

用户报告 SukiSU-Ultra 内核刷入后停在一加 Logo，恢复已备份的 `boot_a` 后可以正常开机。Recovery 可以启动，但 pstore 为空，`/proc/last_kmsg` 不存在。最初没有 panic 栈，不能仅凭源码猜测根因；后续已在用户原始失败镜像的机器码中确认挂载路径的确定缺陷，见下文。

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

## Minimal 与 ADB-root 已完成实机验证（2026-11-11）

- Minimal 构建 `42829399023` 已完成临时启动、管理器 Working 和永久刷入验证。
- ADB-root 构建 `42850640978` 在相同基线上仅新增 `CONFIG_KSU_FEATURE_ADBROOT=y`，嵌入配置逐项比较及 AVB hash 验证通过。
- 先临时启动 ADB-root，完整 `/proc/version` 匹配 `Tue Nov 10 16:10:47 UTC 2026`；不能只看相同的 `uname -r`。
- 管理器启用 ADB Root 后，`adb shell id` 为 `uid=0`、域 `u:r:ksu:s0`；adbd 的实际 UID/GID 全为 0，maps 包含 `libadbroot.so`，dmesg 显示 `adb_root: set to 1` 与 `escape to root for adb`。
- 经用户授权永久刷入 `boot_a` 后，正常重启再次验证启动身份、root 和分区回读 SHA256：`b360977005f539a596d561dabeb212ac35aec5f590db07b51dd817d53da7a6dd`。
- 该阶段 ccache 命中 `4000/4005`（99.88%）；只表示可缓存的编译任务，不能用于承诺总耗时。

## ADB-root + KPM 组合候选

不是两个互斥的功能版本：`build-oneplus-9r-sukisu-kpm.yml` 和对应 profile 同时设置 `CONFIG_KSU_FEATURE_ADBROOT=y`、`CONFIG_KPM=y`，继续关闭 SUSFS/debug。构建 `42860708191` 已成功并完成下述实机验证。

修正旧 KPM 后处理链：固定版本的 `patch_linux` 实测可以退出 0 并产出 oImage，但日志中 kpimg 只有 `0x10`、版本为 0。不能用退出码或文件存在证明 KPM 生效。公开 release 0.14.0 的源码 ABI 也不是当前 SukiSU 要求的 ABI 2。

现在从 KernelPatch 提交 `1c5b608916357ac86a94cc736e235db1fac4a29d` 同源构建真实 `kpimg` 与 `kptools`，ARM 编译器归档固定 SHA256。先检查两个头文件的实际数字 ABI 和三个 framing tag，再检查 payload 大小、版本、架构及 release 属性；只对启用 `CONFIG_KPM=y` 的 arm64 Image 执行后处理。随机 legacy key 经 stdin 传递，不写 argv 或清单。输出检查 `patched=true`、内嵌配置未变、模块数为 0，通过后才原子替换 Image。保留组件和输入/输出 SHA256 诊断清单。

实机结果：临时启动组合镜像后 `sys.boot_completed=1`，完整 `/proc/version` 匹配 `Tue Nov 10 17:10:32 UTC 2026`。ADB-root 为 enabled 且 shell UID 0；`ksud extension get kpm` 返回 available、ABI 2，`ksud kpm version` 返回 `3584 (17:10:15 Nov 10 2026)`，`ksud kpm num` 为 0。dmesg 显示 `sukisu_kpm_supercall_install done: 0`。没有加载模块。

组合 boot SHA256：`c125497903c575309506468c18eae915a38b70e22eb072b1dfabd978176e706a`。本次没有永久刷入，回读 `boot_a` 仍等于上面已验证的 ADB-root 镜像。KPM 后处理会增加其他 `Linux version` 格式串，提取构建身份必须匹配具体 release 的完整 banner，不能取第一个 `Linux version` 字串。

“完整”必须按当前内核支持范围限定：该固定 SukiSU 源码的 SELinux Hide 由 `LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0)` 保护，4.19 不包含；当前管理器也报告 AVC Spoof 不支持。不能将所有显示 Unsupported 的选项都归因于尚未集成 SUSFS，也不能把配置开关齐全等同于每项运行时功能已验证。

## SUSFS 组合诊断阶段

`build-oneplus-9r-sukisu-susfs.yml` 从上述组合基线新增原生 4.19 SUSFS 功能；暂未完成实机验证。它不使用旧整套构建配置，保持原编译器、原 vermagic、ADB-root、KPM 和严格配置比较。

- 继续使用已验证的 exec/read/fstat/reboot hooks，只追加 SUSFS 所需的 UID hook。UID hook 在凭据校验成功后、commit 前执行一次，使用解析后的实际 UID，而非可能为 `-1` 的 syscall 参数。旧 Suki 专用 hook 中重复三次的任务状态处理已移除，并同步 fstat 和声明顺序修复。
- 启用有原生实现的 path/mount/kstat/uname/cmdline/open_redirect 等；禁用兼容层没有实现的 SUS_MAP。v2 的动态 mount 开关、AVC 和 map 兼容入口返回 `EOPNOTSUPP`，不能用“调用不报错”伪装功能有效。
- 修正 `strlen` 的 printk 格式为 `%zu`，检查兼容层的 usercopy 返回值，保留 `CONFIG_CC_WERROR=y`。
- 用户态 `ksud susfs` 自带 status/version/variant/features 查询，可先直接验证内核接口，无需为了显示支持而安装额外模块。
- `tests/susfs_device_probe.c` 是可选的 arm64 用户态实机探针，不是内核/KPM 模块。先查询 version/variant/features，查询失败时不做任何修改；查询成功后短暂改变 uname 的 release，立即恢复原 release/version，并对真实 syscall 结果做比较。它不写持久配置，不改分区/授权/SELinux。已在无 SUSFS 的 ADB-root + KPM 基线上确认查询失败、未尝试修改。正向实机结果仍待 SUSFS 候选启动。

### 原失败镜像中的挂载失败路径已确认

SUSFS 构建 `42866305499` 的严格编译在 `fs/namespace.c:1059` 拒绝了 `#endif\tif (!mnt)`：补丁缺少换行，预处理器把 `if (!mnt)` 当成指令尾部多余 token 丢弃，原本仅供分配失败执行的 `return ERR_PTR(-ENOMEM)` 变成无条件返回。这不是关闭 WERROR 可以解决的问题。

进一步检查用户原始 `boot_a-failed.img` 中提取的内核（SHA256 `c2ea49338b7ee868d9a93c9e54cc1145fbc7ce2450a35b8b6884b910d48a69f1`），使用固定 KernelPatch 的 kallsyms 解码和 ARM objdump 得到实际机器码：

```text
vfs_create_mount: 0x0049f7a8 .. 0x0049f807
0x0049f7e8  bl   0x0049f808             # alloc_vfsmnt
0x0049f7f0  mov  x0, #0xfffffffffffffff4 # ERR_PTR(-ENOMEM), -12
0x0049f7fc  ret
0x0049f800  mov  x0, #0xffffffffffffffea # root=NULL 时 -EINVAL
0x0049f804  ret
```

函数不存在成功返回路径，分配结果被忽略；该缺陷已进入用户刷入的二进制，足以阻止正常挂载/启动，不只是源码推测。尚不能据此排除同时存在其他故障。

提交 `1caa24d` 恢复独立的条件语句，增加真实补丁片段的 C 回归测试：SUSFS 开/关 × KSU/普通域 × 分配成功/失败，同时检查所有补丁新增 `#endif/#else` 行不吞掉 C 语句。43 项测试通过。新构建 `42870965525` 仍需实机验证，原失败镜像保留不动。

### 首次 SUSFS 候选的运行时结果与管理器连接修复

构建 `42870965525` 后续已完成临时启动：`sys.boot_completed=1`，完整构建时间为 `Tue Nov 10 18:09:07 UTC 2026`。ADB-root UID 0、KPM ABI 2/loader 0xe00/模块数 0 均正常；SUSFS 返回 `true`、`v1.5.9-v2compat`、`NON-GKI`。实机探针成功观察到 uname 变化，并恢复原 release/version。`boot_a` 回读仍是永久 ADB-root 镜像，未刷写新候选。

但是不能将这轮标为完整通过：官方管理器显示 Unsupported。内核日志确认管理器签名通过、UID 10118 已识别；管理器进程仍为 `Seccomp: 2`，没有 KSU 驱动 FD。与之相对，root 启动的 `ksud` 可以查询所有内核接口。

追踪发现 `kernel/selinux/rules.c` 仅在 ≥5.10 的策略分支调用 `susfs_set_batch_sid()`，旧内核分支没有调用。通用的 `cache_sid()` 初始化另一组缓存，不能代替 SUSFS 专用 SID；实机也没有 SUSFS 批量 SID 初始化日志。SUSFS 的 zygote/管理器 UID hook 因而无法正确匹配域，挂载分类也未得到正确 SID。

提交 `624bc60` 在旧内核策略更新完成、锁已释放的 `out_flush` 路径补上 SUSFS SID 初始化。未修改管理器签名检查、包名、授权列表或 SELinux enforcing 状态。构建 `42876653991` 用于验证修复，必须重新检查管理器 Working、ADB-root、KPM、SUSFS 和实际挂载路径，不能只复查 root CLI。

另：锁屏截图一度全黑，日志证明是设备面朝下触发约两秒自动息屏，不是 UI 崩溃。短暂开启 USB 保持唤醒以验证 UI 后已恢复原设置；未持久化用户解锁信息。

### 三项组合与官方管理器最终验证通过

构建 [42876653991](https://github.com/XiaoliChan/KernelSU_Action/actions/runs/42876653991)（源码提交 `624bc60`）通过临时启动与管理器验证：

| 检查 | 实测结果 |
| --- | --- |
| 启动身份 | `boot_completed=1`，完整 `/proc/version` 为 `Tue Nov 10 18:44:01 UTC 2026` |
| ADB-root | `enabled`，shell `uid=0`，SELinux 域 `u:r:ksu:s0` |
| KPM | available、ABI 2、loader `3584 / 0x0e00`；模块数 0，未加载任何 KPM 模块 |
| SUSFS | `true`、`v1.5.9-v2compat`、`NON-GKI`；uname 实际改变并立即恢复，重复测试通过 |
| 官方管理器 | **Working**，版本 `41168-6`；首页同时显示 KPM 0、SUSFS Inline Hook |
| 管理器连接 | UID 仍为 10118、`Seccomp: 0`、FD 指向 `anon_inode:[ksu_driver]`；日志确认 install fd for manager |
| SID 修复 | zygote、zygote_next、ksu、init、priv_app 的 SUSFS SID 初始化日志均存在 |
| 永久分区 | `boot_a` SHA256 仍为已验证的 ADB-root 镜像，没有永久刷入组合候选 |

```text
组合 Image SHA256: 03d596700f5f17ac6a8136f4f7f141d8af06c30177517b26710818082ec63293
临时 boot SHA256:  3527d5df361ebdc31535df986d107103cc80164d662039d5a7cea3d5e227fc56
永久 boot_a SHA256:b360977005f539a596d561dabeb212ac35aec5f590db07b51dd817d53da7a6dd
```

这是**同一个**内核中的 ADB-root + KPM + SUSFS，不是分散的互斥镜像。仍需区分能力验证与完整覆盖：KPM 按授权只测 probe/version/模块数；SUSFS 版本为 4.19 原生实现的 v2 兼容层，并非全部上游 v2 功能。未改应用授权、未安装新模块、未更改全局 SELinux enforcing；临时显示设置已恢复。组合产物只在 Actions Artifacts 中，未自动新增 Release。
