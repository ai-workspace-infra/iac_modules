#!/usr/bin/env bash
# 共享一键联动脚本：YAML 声明 -> 渲染 TF -> apply -> CMDB/inventory ->（可选）Ansible
#
# 位置: vultr-vps/scripts/provision.sh （与 generate.py 同目录，可被多套资源声明复用）
#
# 环境变量:
#   TF_VAR_vultr_api_key   必填
#   RESOURCES              资源声明 YAML（默认 config/resources/ai-workspace-hosts.yaml）
#   WORKDIR                terraform 运行目录（默认 envs/ai-workspace）
#
# 用法:
#   export TF_VAR_vultr_api_key=xxxx
#   ./provision.sh                          # 渲染+创建+生成 inventory
#   ./provision.sh ping                     # 之后对 ai_workspace 组跑 ping
#   ./provision.sh playbook setup-ai-workspace-all-in-one.yml
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VULTR_VPS_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# vultr-vps -> terraform-hcl-standard -> iac_modules -> ai-workspace-infra
REPO_ROOT="$(cd "${VULTR_VPS_ROOT}/../../.." && pwd)"
PLAYBOOKS_DIR="${REPO_ROOT}/playbooks"
DYN_INV="${PLAYBOOKS_DIR}/inventory/terraform_cmdb.py"

RESOURCES="${RESOURCES:-${VULTR_VPS_ROOT}/config/resources/ai-workspace-hosts.yaml}"
WORKDIR="${WORKDIR:-${VULTR_VPS_ROOT}/envs/ai-workspace}"
GEN=("python3" "${SCRIPT_DIR}/generate.py")

echo "==> [1/4] render (${RESOURCES##*/} -> ${WORKDIR})"
"${GEN[@]}" render --resources "${RESOURCES}" --workdir "${WORKDIR}"

echo "==> [2/4] terraform init & apply"
terraform -chdir="${WORKDIR}" init -input=false >/dev/null
terraform -chdir="${WORKDIR}" apply -auto-approve -input=false

echo "==> [3/4] inventory (terraform output + YAML -> cmdb.json + inventory.ini)"
"${GEN[@]}" inventory --resources "${RESOURCES}" --workdir "${WORKDIR}"

echo "==> [4/4] 完成。生成: ${WORKDIR}/{cmdb.json,inventory.ini}"

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
