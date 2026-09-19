# AutoRecon 外部协作网关

本服务给外部协作者提供：上传去标识影像、调用服务器已注册程序、查询进度、下载结果。
它是独立进程，不替换现有本机 Dashboard。现有 `127.0.0.1:8899` Dashboard **没有认证**，不要对公网开放。

## 本机已确认的环境

| 项 | 结果 |
| --- | --- |
| 主机 | `nfsclient-2.nfs.sist.shanghaitech.edu.cn`（上科大 SIST NFS 计算节点） |
| 系统 | Ubuntu 22.04.5，非特权用户 `huangwei`，无 sudo |
| 地址 | `10.15.89.115`、`12.1.11.15`，无入站公网 IP |
| 出站 | HTTPS 可达；本机 Clash 代理 `127.0.0.1:17890`；NAT 出口约 `74.211.105.11` |
| 现有后端 | `python -m agentic.dashboard_cn`，仅本机，可指定任意路径 |
| 隧道软件 | 未安装 cloudflared / ngrok / Tailscale / frp |
| 磁盘 | `/mnt/sda` 约 1.7T 可用（已用 97%），必须限额并定期清理 |

## 组网方案比较与选择

| 方案 | 访问便利性 | 上传限制 | 稳定性 | 维护 / 预算 | 医学数据 |
| --- | --- | --- | --- | --- | --- |
| 私有组网（校园网 + 学校 VPN / Tailscale） | 需加入 VPN 或校园网 | 无第三方体积上限 | 高 | 校园 VPN 无额外费用；Tailscale 个人档免费 | 数据不经过公共反向代理，优先 |
| 托管隧道（Cloudflare Tunnel / ngrok） | 公网 HTTPS，最省事 | Cloudflare 免费边缘约 100MB/请求；需分块或付费 | 依赖出站长连接 | 账号免费起步 | 影像会经第三方，伦理/单位政策风险高 |
| 自建公网网关（云主机 + 反向 SSH/frp） | 自定义域名，体验好 | 仅受云主机带宽和本服务限额约束 | 高 | 约 ¥30–100/月 + 证书 | 需自行做 TLS 与访问控制 |

**当前选择：先只绑定 `127.0.0.1` 完成本机验证。对外开放优先走学校 VPN / 校园网或 Tailscale，而不是托管隧道。**

依据：

1. 本机没有可入站公网地址，不能直接做端口映射。
2. 胎儿脑 MRI 单例常超过 100MB，免费 Cloudflare 代理不适合作为主上传通道。
3. 研究影像经第三方隧道可能违反单位数据管理要求。
4. 无 sudo、无 Docker、无 Nginx，不能在本机做 80/443 网关。
5. 出站 HTTPS/SSH 可用，因此以后若必须服务校外且不能用 VPN，再考虑「云主机 + 反向 SSH」，而不是先买隧道套餐。

## 启动

```bash
cp config/service.env.example config/service.env
# 保持 AUTORECON_GATEWAY_HOST=127.0.0.1
scripts/run_gateway.sh
```

首次启动会把管理员密码写到 `.runtime/gateway/bootstrap_admin.txt`（权限 600）。
浏览器访问 `http://127.0.0.1:19001`。局域网直连（`0.0.0.0:19001`）时，医生端操作说明见 [../user/DOCTOR_TUTORIAL.zh-CN.md](../user/DOCTOR_TUTORIAL.zh-CN.md)。

创建普通用户：

```bash
python -m service add-user --username collaborator --role user
```

允许的程序只有 `input_check` 与 `run_pipeline`。参数必须落在白名单内；图谱路径由服务器按孕周选择，用户不能指定任意文件系统路径，也不能提交 shell 命令。

## 对外开放前必须完成

1. 本机测试：认证失败、跨用户隔离、分块上传、非法程序/参数拒绝、任务超时与清理。
2. 你确认学校是否允许该节点对校园网或 VPN 用户监听高位端口。
3. 如需 Tailscale / 云主机 / 域名 / Cloudflare，由你完成账号、采购和单位审批；本服务不会自动安装隧道。
4. 在绑定非回环地址之前，确认管理员密码已轮换，且 8899 Dashboard 仍只听 `127.0.0.1`。
