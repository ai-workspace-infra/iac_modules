# Akamai Cloud/Linode UAT Terraform workdir

这是 Terraform 运行目录。实际资源声明来自 GitOps：

```text
resources/<project>/uat/akamai/*.yaml
```

渲染产物、state、CMDB 和 inventory 均由 `.gitignore` 排除。请通过共享脚本
执行 `render`，不要在此目录手工维护 provider 或资源块。
