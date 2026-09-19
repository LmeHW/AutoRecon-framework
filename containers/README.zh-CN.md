# AutoRecon 共享容器

运行时 SIF 文件保存在项目根目录的 `.runtime/containers/`，不提交到版本控制。
可复现的本地环境定义保存在 `containers/definitions/`。

## FROST

`frost.def` 将已验证的 `/home/wangxiao/.conda/envs/frost` 原路径封装进只读 SIF，避免
重新定位导致 tiny-cuda-nn、PyTorch CUDA 扩展或脚本 shebang 失效。FROST 源码不复制进
镜像；运行时由 pipeline 将共享工作区 bind 到容器，因此代码更新无需重建环境。

构建：

```bash
export AUTORECON_RUNTIME_ROOT=/mnt/sda/huangwei/projects/AutoRecon/.runtime
export APPTAINER_CACHEDIR="$AUTORECON_RUNTIME_ROOT/model_cache/apptainer"
export APPTAINER_TMPDIR="$AUTORECON_RUNTIME_ROOT/tmp/apptainer"

/mnt/sda/huangwei/conda_envs/apptainer/bin/apptainer build \
  "$AUTORECON_RUNTIME_ROOT/containers/frost.sif" \
  containers/definitions/frost.def
```

GPU smoke test：

```bash
apptainer exec --cleanenv --nv \
  "$AUTORECON_RUNTIME_ROOT/containers/frost.sif" \
  /home/wangxiao/.conda/envs/frost/bin/python -c \
  'import torch, tinycudann; print(torch.cuda.is_available())'
```

## Extraction 与 tissue nnU-Net

两个定义采用与 FROST 相同的不可重定位快照策略。模型权重保留在项目的
`pipeline/Unet/.../nnUNet_results` 和 `pipeline/models/.../nnUNet_results`，运行时只读
bind，避免在环境镜像中重复保存大权重。

```bash
apptainer build "$AUTORECON_RUNTIME_ROOT/containers/extraction_nnunet.sif" \
  containers/definitions/extraction_nnunet.def
apptainer build "$AUTORECON_RUNTIME_ROOT/containers/tissue_nnunet.sif" \
  containers/definitions/tissue_nnunet.def
```
