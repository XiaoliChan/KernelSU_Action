# OnePlus 9R 补丁审查

维护说明：原版 KernelSU 的 9R workflow 和设备配置已按用户要求移除。下文“三个版本”的审查、构建和发布记录为历史证据；当前保留 SukiSU-Ultra、BakaSU 及阶段性诊断入口。

## AnyKernel3 发布包更正

首次三份自动 Release 的内核编译成功，但安装脚本仍包含上游 tuna 示例，且槽位变量误写为小写；这说明此前打包测试覆盖不足。三个旧 Release 已删除，不能继续使用已下载的旧 ZIP。
修正版使用本仓库的 kernel-only 安装模板及固定的 AnyKernel3 工具提交 `41f04bdb4ee30a44e429c2c1131d5e8bb32b15f1`，移除示例 ramdisk/patch/modules 内容，启用 lemonades 设备校验及 `IS_SLOT_DEVICE=1`，显式选择活动槽位。
新 ZIP 保留现有 ramdisk（包含可能存在的 Magisk），不执行示例 init/fstab 修改，不额外写 vbmeta 分区。

重新发布复用了 run `42744806788`、`42744812851`、`42744818437` 已成功编译的 Image，而非声称重新编译；打包前后及下载原 Artifact 的内核哈希一致。
18 项本地回归通过；对三份实际新 ZIP 分别执行其真实 `setup_ak` 槽位解析器，在沙箱分区文件上验证 A、B 和缺失槽位三种情况。读写函数使用桩，不涉及真实设备写入。缺失槽位会在写入前中止。
`scripts/verify-anykernel.py` 在默认打包链路中检查脚本策略、示例残留、工具权限、ZIP CRC 和 Image 哈希；旧 ZIP 被该检查拒绝。尚无实机启动验证。

## 内核补丁修复记录

审查基线：`9057d14`。范围为 `patches/oneplus-9r/` 以及三个设备配置的接入链路。
原审查发现的 5 项问题现已完成代码修复与本地回归验证。以下问题描述和行号保留为修复前基线证据，不代表当前代码仍原样存在；完整内核编译交由三个 GitHub Actions 工作流，设备启动与实际功能仍需实机验证。

## 修复结果

- 路径、kstat、open_redirect 拆出内核结构入口，v1 用户入口保留；v2 转换不再回写整个 v1 结构，只更新自己的 `err`，并拒绝未终止字符串。
- 非 root 应用分类统一使用 `task_struct.susfs_task_state` bit 24；v2 已卸载状态仍使用 thread flag 33。现代分支的 setresuid hook 根据 no-su 状态显式更新分类，避免 faccessat 中按 UID 一刀切。
- faccessat 和 stat 把修改后的 `struct filename` 交给 `filename_lookup` 消费；保留 LOOKUP_EMPTY、符号链接标志和 ESTALE 重试，不额外 putname。
- exec hook 移到 native/compat 共用的 `do_execveat_common`，在执行前调用，传递真实 fd/flags 地址，覆盖 execve 与 execveat。
- kstat 路径解析和分配在锁外完成，更新在锁内原位重挂哈希；两个哈希读者也持同一把锁，防止替换释放与读取并发。
- 同时修复普通 sus_path 被未初始化的空目录前缀误匹配，以及 `d_path` 错误指针判断。

本地共 13 项测试通过，其中新增 5 项补丁回归包含对真实函数提取代码的 C 编译执行、UBSan、用户缓冲区哨兵、错误回传、状态隔离及 hook 参数传递；另有锁区静态检查。
三套配置均从干净上游文件应用 path_umount、hooks、SUSFS、hide_stuff 及分支 fixups 并完成 defconfig 注入，没有补丁拒绝。

验证源码：

| 组件 | 引用 |
| --- | --- |
| LineageOS SM8250 lineage-24.0 | `078365e5318de0a30a41f9707070b610bcd20f13` |
| KernelSU | `v0.9.5` |
| BakaSU main | `548d1dda060ca198823d8808804d01f5209ef4a9` |
| SukiSU-Ultra builtin | `1cfa57340590971cba7521ed536da8ebbedc5f0a` |

两个现代分支的设备配置已固定到上述提交，避免重建时接口随分支变化。内核补丁应用验证使用完整的受影响文件集，不是本地完整内核编译。

## P1 v2 路径请求回写超过调用方结构大小

位置：`patches/oneplus-9r/fs/susfs_compat.c:83-103`，结构定义在同文件 `:42-45` 与 `include/linux/susfs.h:29-33`。

`compat_add_sus_path()` 先读取 v2 请求，再把整个 v1.5.9 结构写回同一个用户地址。
按代码声明的 LP64 布局，v2 请求为 260 字节，而 v1.5.9 请求为 272 字节，回写越界 12 字节。
若相邻用户内存可写，`copy_to_user()` 不会知道原对象只有 260 字节，会覆盖后续对象；若跨入不可写页，则部分回写后失败。
它还破坏原请求布局，且没有把底层返回值写回 v2 `err`。

建议：把 v1 实现拆成接收内核结构的内部函数；分别由 v1/v2 用户入口拷贝和转换，不能借用调用方缓冲区作为结构转换工作区。kstat 和 open_redirect 包装也应一起移除这种回写再读取的设计，并正确回传错误。

本地从原文件提取两个结构，以 `cc` 编译 `sizeof` 探针，输出：

```text
v2=260 v159=272 overwrite=12
```

此测量采用宿主 LP64 布局，与这两个结构在目标 arm64 下的基本类型大小及对齐相符；没有执行目标内核中的 `copy_to_user`。

## P1 非 root 应用与已卸载挂载共用同一状态位

位置：`patches/oneplus-9r/include/linux/susfs_def.h:63,81-86,115`；`fs/susfs_compat.c:297-330`。

`TIF_NON_ROOT_USER_APP_PROC` 与 `TIF_PROC_UMOUNTED` 均为 33，且均读写 `thread_info.flags`。
调用 `susfs_set_current_proc_umounted()` 会同时使 `susfs_is_current_non_root_user_app_proc()` 返回真，反向也成立，两个本应独立的状态无法区分。
另有 dcache 补丁和 faccessat hook 使用 `current->susfs_task_state` 的 bit 24，与上述 thread flag 并非同一存储；不能假定设置其中一个就会启用所有隐藏路径。

建议：统一进程状态来源，为独立语义分配互不重叠的位，并核查 fork、UID 变更及清除路径。至少测试仅设置任一状态时，另一状态仍为假。

## P1 faccessat 和 stat 丢弃 hook 修改后的路径

位置：两份 `kernel_hooks/kernel-4.19*.patch:60-71,105-112,123-130`。

新增代码执行 `getname(filename)`，将独立的 `struct filename *ksu_name` 交给 hook 修改，然后直接 `putname(ksu_name)`。
后续 `do_faccessat()` / `vfs_fstatat()` 仍使用原始用户指针 `filename`，没有消费修改后的内核路径。
因此，只要所选分支通过该参数做 su 路径重定向，重定向就不会传给真正的文件检查；fd、mode、flag 的修改不弥补路径丢失。

建议：在真正接收 `struct filename` 的 VFS 路径接入 hook，保留正确的所有权和 `putname` 时机。用会把不存在路径改成有效路径的桩 hook 验证下游实际消费的参数；随后再对所固定的 KernelSU 提交做集成验证。

## P2 32 位 exec hook 位于 return 之后

位置：两份 `kernel_hooks/kernel-4.19*.patch:36-44`。

`compat_do_execve()` 中先 `return do_execveat_common(...)`，后面才插入 `ksu_handle_execveat()`。
该新增调用不可达，32 位 compat exec 路径不会执行它。两份补丁的文本探针均确认这个顺序。

建议：把 hook 放到调用 `do_execveat_common` 前，并使用真实的局部 fd/flags 变量传址。
同文件 64 位 hook 的 `(int *)AT_FDCWD` 也不是有效的 `int *`，是否触发故障取决于上游 handler 是否解引用，需对固定分支进一步核对，不能只改不可达代码就认为完成。

## P1 持有自旋锁时进行可能睡眠的路径解析与分配

位置：`patches/oneplus-9r/fs/susfs.c:638-645`；被调用的 `susfs_update_sus_kstat_inode()` 从 `:504` 开始。

更新已有 kstat 项目时，代码持有 `susfs_spin_lock` 调用内部含 `kern_path()` 的辅助函数，并进行 `kmalloc(..., GFP_KERNEL)`。
路径解析和该分配允许睡眠，与自旋锁临界区不兼容；内存压力或路径查找阻塞时可能导致 atomic-context 调度告警或挂死。该路径由 v1 入口及 v2 转发共同使用。

建议：锁外解析路径和分配，锁内只做短暂的查找、校验及替换；同时处理无锁哈希读者的对象生命周期，不应仅把 GFP_KERNEL 改成 GFP_ATOMIC。用 lockdep / DEBUG_ATOMIC_SLEEP 的目标构建验证。

## 仍需设备或固定上游提交验证的风险

- `fs/susfs_compat.c:352-371` 用单个全局 UID 和 pending 位近似多请求队列，连续请求会覆盖。workqueue 回调也未保存调用进程的挂载命名空间；仅传 UID 不等于切换 namespace。需要对实际分支的卸载函数和调度点核对。
- sus_map、sdcard monitor、AVC spoofing、priority UID filter 等仍为空实现。Kconfig 存在或 manager 调用不报错，不代表功能有效。
- 已取得三个 KernelSU 的 kernel/ 源码快照和内核受影响文件集并验证 clean apply；未做本地完整内核编译或设备启动测试。实机验证应保留上述构建引用和实际 Actions 日志。

## 本次发布链路验证

- 三个设备工作流默认发布，可显式关闭；未新增 push 或定时构建触发器。
- Release tag 区分设备、KernelSU 分支、构建时间、run ID、attempt，绑定触发构建的仓库提交。
- AnyKernel3 在构建端先打 ZIP，发布阶段直接复制；增加 ZIP 完整性检查、必需产物检查和 SHA256SUMS。
- 上传目录不保留原权限，依据 [upload-artifact 官方说明](https://github.com/actions/upload-artifact#permission-loss) 改为预先归档。
- 本地验证：8 项发布测试、6 份配置解析、Shell 语法、actionlint 与 `git diff --check` 通过；未实际创建远端 Release。

回归命令：

```bash
python3 -m unittest discover -s tests -v
for f in scripts/*.sh patches/*.sh; do bash -n "$f" || exit; done
for f in config.env config/*.env; do CONFIG_ENV="$f" bash scripts/config.sh >/dev/null || exit; done
actionlint
git diff --check
```

测试依赖 Python 3、PyYAML、git、zip、unzip；本次本地 actionlint 使用 `-shellcheck=`，ShellCheck 未安装，未宣称通过该检查。
