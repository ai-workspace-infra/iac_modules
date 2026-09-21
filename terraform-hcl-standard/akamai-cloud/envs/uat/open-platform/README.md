# open-platform

独立且常驻的 UAT Terraform workdir，承载迁移后的 `observability.svc.plus` 与
`vault.svc.plus`。日常清理不得 destroy 此 namespace。旧 observability 主机不是
本 state 的资源。
