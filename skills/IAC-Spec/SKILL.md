---
name: IAC-Spec
description: |
  Infrastructure-as-Code YAML Rendering Pattern and Coding Standards for iac_modules. 
  Dictates how AI should read/write infrastructure templates, isolate states by environment, and interoperate with configuration layers.
---

# Infrastructure-as-Code (IAC) 规范指南

本规范专门用于指导在 `iac_modules` 仓库中进行自动化与基础设施代码（IaC）建设的最佳实践与红线原则。当 AI 进行任何云原生资源的修改与新增时，必须严格遵守以下守则。

## 1. 声明式 YAML 驱动与渲染隔离
**原则**: 基础设施的拓扑变量、机器规格与具体参数，绝对禁止硬编码于 HCL (Terraform) 文件中。
- **配置分离**: 强调多环境（`sit` / `uat` / `prod`）的具体拓扑必须在对应的 `config/resources/[env]/*.yaml` 中清晰定义。
- **状态隔离**: Backend State 的 key 或者 namespace，强制要求按照环境级目录存放（例如：`uat/databases.tfstate`），绝不可跨环境复用状态空间。
- **构建机制 (IaC + Python Jinja2)**: 目前架构使用 Python 脚本 (`scripts/generate.py render`) 结合 Jinja2 模板解析 YAML 并自动输出 `.tf.json` 形式的配置文件。所有针对具体环境的逻辑修改，应优先考量在 YAML 拓扑或渲染逻辑中完成，而非直接修改基础模块。

## 2. HCL 代码纯净度与限制
**原则**: Terraform HCL 代码仅仅作为最底层的资源“声明书”，应保持极致的简洁和纯粹。
- **弱化分支判断**: 强烈禁止在 HCL 中过度使用复杂的逻辑分支（如多重嵌套的 `count`、复杂的 `dynamic` 块与条件表达式）。如果遇到业务级的条件判断，应将其上浮至 Python Jinja2 的渲染层去决策，使最终生成的 HCL 趋近纯声明式结构。
- **禁止内嵌脚本**: 绝对禁止在 HCL 定义（例如 `local-exec` provisioner 或 `null_resource` 中）内嵌或编写 `shell`、`python` 等执行脚本。

## 3. 互操作性设计 (IaC ↔ Config-as-Code)
**原则**: 明确边界，解耦职责，通过标准的凭证库（Vault）与静态清单进行传递。
- **职责边界 (CMDB)**: IaC (Terraform) 层的唯一职责是分配与建立云上的计算、网络、存储等资源，并在输出阶段（Outputs）自动生成标准化的结构资源清单（如 `cmdb.json`）。IaC 不负责具体的软件系统配置。
- **状态解耦桥梁**: 跨阶段传递的敏感凭证（如 IaC 初始化数据库时随机生成的初始密码），绝对禁止写入本地文件向后传递，而是必须由 IaC 直接推送到 HashiCorp Vault 的 Secret 引擎中；后续 Ansible Playbooks 将仅通过 Vault 去安全提取状态。
