# Xiaomi SM8750 kernel modules

Redmi K90 (`annibale`) OSS 内核的外部模块工作仓库。

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

定向目标文件编译不等于完整模块链接；尚未完成整套外部模块、ABI 或真机验证。
内部 `qcom/opensource` 路径保留。继承的 `//vendor/qcom/sm8750-modules`
Bazel 标签尚待构建工作区接入。

仓库组合、同步方式及总体状态见
[README.annibale.md](https://github.com/yuwenhua653/android_kernel_xiaomi_sm8750/blob/annibale/README.annibale.md)。
