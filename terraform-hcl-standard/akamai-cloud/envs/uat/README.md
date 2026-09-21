# Akamai Cloud/Linode UAT Terraform workdir

这是 UAT Terraform workdir 的父目录。实际资源声明来自 GitOps，并必须按以下
六个目录隔离：

```text
web-saas/
open-platform/
ai-workspace/
agent-proxy-jp/
agent-proxy-us/
agent-proxy-sg/
```

禁止继续把本目录自身作为共享 `selfhost` workdir。实际资源声明来自 GitOps：

```text
resources/<project>/uat/akamai/*.yaml
```

渲染产物、state、CMDB 和 inventory 均由 `.gitignore` 排除。请通过共享脚本
执行 `render`，不要在此目录手工维护 provider 或资源块。
