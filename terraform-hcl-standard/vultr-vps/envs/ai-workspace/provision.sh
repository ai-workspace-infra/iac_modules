#!/usr/bin/env bash
# 一键联动：YAML -> 渲染 TF -> apply -> 生成 CMDB/inventory ->（可选）跑 Ansible
#
# 用法:
#   export TF_VAR_vultr_api_key=xxxx
#   ./provision.sh                          # 渲染+创建+生成 inventory
#   ./provision.sh ping                     # 之后对 ai_workspace 组跑 ping
#   ./provision.sh playbook setup-ai-workspace-all-in-one.yml
set -euo pipefail

ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${ENV_DIR}/../../../../.." && pwd)"
PLAYBOOKS_DIR="${REPO_ROOT}/playbooks"
DYN_INV="${PLAYBOOKS_DIR}/inventory/terraform_cmdb.py"

echo "==> [1/4] generate.py render (hosts.yaml -> generated_hosts.tf + tfvars)"
python3 "${ENV_DIR}/generate.py" render

echo "==> [2/4] terraform init & apply"
terraform -chdir="${ENV_DIR}" init -input=false >/dev/null
terraform -chdir="${ENV_DIR}" apply -auto-approve -input=false

echo "==> [3/4] generate.py inventory (terraform output + YAML -> cmdb.json + inventory.ini)"
python3 "${ENV_DIR}/generate.py" inventory

echo "==> [4/4] 完成。生成文件:"
echo "    ${ENV_DIR}/cmdb.json"
echo "    ${ENV_DIR}/inventory.ini"

action="${1:-none}"
case "${action}" in
  none)
    echo "可手动执行: ansible ai_workspace -i ${DYN_INV} -m ping"
    ;;
  ping)
    ( cd "${PLAYBOOKS_DIR}" && ansible ai_workspace -i "${DYN_INV}" -m ping )
    ;;
  playbook)
    pb="${2:?用法: provision.sh playbook <playbook.yml>}"
    ( cd "${PLAYBOOKS_DIR}" && ansible-playbook -i "${DYN_INV}" "${pb}" )
    ;;
  *)
    echo "未知动作: ${action} (支持: none|ping|playbook)" >&2
    exit 1
    ;;
esac
