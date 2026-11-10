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
2. 使用可开机内核的原始配置快照和 Clang r596125，全 LLVM 工具链。
3. 不安装 KernelSU，不应用任何 SUSFS、manual-hook、path_umount 或 hide_stuff 补丁。
4. 生成配置后逐项比对；有差异就停止，不把偏离的配置当作有效对照组。
5. 只上传诊断 Artifacts，权限仅 `contents: read`；没有 Release 发布入口。

对照组编译成功仍不代表实机验证成功。先验证基线能启动，再分阶段引入 root 与 SUSFS；不要继续轮流刷当前三个功能齐全的版本来猜原因。
