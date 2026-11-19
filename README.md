# Xiaomi SM8750 kernel modules

Redmi K90 (`annibale`) OSS 内核的外部模块工作仓库。

当前进度：[R41 实际构建验证](Documentation/xiaomi/annibale-r41-build.md)；
[验证记录](Documentation/xiaomi/annibale-r41-validation.json)。
Linux 6.6.144 内核、411 个内核模块和 93 个外部模块实际构建通过；
TFA/SIA 分别选取 217/218 个模块完成离线镜像与回读检查，32 组最终 DT 检查通过。
315 项独立测试通过。SLA 已单独完成 .ko 链接、modpost 和 BTF 验证，仍默认关闭且不装入镜像。
完整 Android 17 ROM、生产 KMI/签名策略及真机功能尚未验证；这些离线产物不可直接刷机。

上一轮：[R40 QESD 管理器整组接入](Documentation/xiaomi/annibale-r40-qesd-managers.md)。
历史记录：[R40 QESD 管理器整组接入：上一轮剩余 7 项输入全部补齐](Documentation/xiaomi/annibale-r40-qesd-managers.md)；
[本轮验证记录](Documentation/xiaomi/annibale-r40-validation.json)。
两份管理器、两份 init、两份 seccomp 和一份 VINTF 一起接入；修正 socket 回复及线程/信号生命周期所需的 seccomp 规则，保留 UNIX socket 与 W^X 限制。76 项相关测试及整组实际提取通过；OS4 选定依赖的版本化强符号离线检查通过。完整原生 ROM、SELinux 编译和真机功能仍待验证。
R38 的独立 eSIM 补充和 R39 的特权 QESD APK/平台签名规则仍需应用；7 → 0 指上一轮剩余输入，不是全部驱动或硬件缺陷已修复。
R37 的电话音频迁移和 OS4 APK 要求 API 37 的构建前检查保留。
SLA 的 R34 对象编译验证已由 R41 的完整模块构建验证补充；运行时验证仍待完成。
原生源码方案与澎湃原厂保留方案分开验证，尚未完成 OSS 真机开机验证。

- 来源：`LineageOS/android_kernel_qcom_sm8750-modules`，`lineage-22.2`。
- 初始提交：`14ab4c38ac7f07d2b807ca7851500da86d2eb56e`。
- 开发分支：`annibale`。
- 源码目录：`kernel/xiaomi/sm8750-modules`。
- Soong import：`kernel/xiaomi/sm8750`。

第一批设备增量：

- `xiaomi/touch/annibale`：小米官方同族 Goodix 9916K + `xiaomi_touch` 的实验移植，默认关闭。Annibale 的原厂 p11 目录没有公开，需继续验证固件、用户空间接口及真机行为。
- `qcom/opensource/camera-kernel`：加入 P11 CSIPHY 专属寄存器表与 compatible，保留 LOS 公共驱动改进。

来源与检查说明：

- [触摸移植](Documentation/xiaomi/annibale-import.md)
- [P11 CSIPHY](qcom/opensource/camera-kernel/Documentation/annibale-csiphy.md)

R8 已完成触摸、相机、显示、音频、NFC、DSP 及公共依赖共 58 个外部模块的
完整链接，并与 410 个验证配置内核模块核对符号 CRC、版本和依赖。
复现入口见 [完整构建说明](Documentation/xiaomi/annibale-full-build.md)。
这不等于整套外部模块、Android KMI、原厂模块兼容性或真机验证。
内部 `qcom/opensource` 路径保留。继承的 `//vendor/qcom/sm8750-modules`
Bazel 标签尚待构建工作区接入。

仓库组合、同步方式及总体状态见
[README.annibale.md](https://github.com/yuwenhua653/android_kernel_xiaomi_sm8750/blob/annibale/README.annibale.md)。
