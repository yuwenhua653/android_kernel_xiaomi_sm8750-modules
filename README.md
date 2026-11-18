# Xiaomi SM8750 kernel modules

Redmi K90 (`annibale`) OSS 内核的外部模块工作仓库。

当前进度：[R36 OS4 相机与 QAPE 旧提取项迁移：19 → 10](Documentation/xiaomi/annibale-r36-camera-qape.md)；
[本轮验证记录](Documentation/xiaomi/annibale-r36-validation.json)。
本轮保留现有相机及 Perf2/QAPE 实现，清理 9 个旧构建输入；不代表新增 9 个驱动或真机功能已修复。
SLA 已通过 ARM64 对象编译和主机故障注入测试，默认关闭，仍需目标内核运行时及 ABI 验证。
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
