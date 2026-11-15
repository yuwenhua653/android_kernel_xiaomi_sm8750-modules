# Xiaomi SM8750 kernel modules

Redmi K90 (`annibale`) OSS 内核的外部模块工作仓库。

- 来源：`LineageOS/android_kernel_qcom_sm8750-modules`，`lineage-22.2`。
- 初始提交：`14ab4c38ac7f07d2b807ca7851500da86d2eb56e`。
- 开发分支：`annibale`。
- 源码目录：`kernel/xiaomi/sm8750-modules`。
- Soong import：`kernel/xiaomi/sm8750`。

当前只完成工作仓库初始化和 Soong 路径迁移，尚未完成 K90 外设驱动
移植或完整模块构建。内部 `qcom/opensource` 路径保留。
继承的 `//vendor/qcom/sm8750-modules` Bazel 标签尚待构建工作区接入。

仓库组合、同步方式及适配状态见
[README.annibale.md](https://github.com/yuwenhua653/android_kernel_xiaomi_sm8750/blob/annibale/README.annibale.md)。
