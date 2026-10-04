#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# 把 Terraform state 与 Vultr 上的事实对齐, 然后才允许 plan/apply/destroy 开始。
#
# 为什么需要这一步: terraform plan 的第一件事是 refresh, 而 vultr provider
# 2.21.0 的 instance Read 只把 "invalid instance ID" 当作资源已消失, 对 Vultr
# 现在返回的 {"error":"instance not found","status":404} 直接抛错。于是只要
# state 里留下一个指向已删实例的 ID —— apply 中途失败、机器被手工清掉、账户侧
# 回收, 都会造成 —— 之后每一次 plan 都在 refresh 阶段硬失败, 且重跑不会自愈:
# 流水线永久卡在 provision, 唯一出路是有人手工 terraform state rm。
#
# 这一步把那件手工操作变成流水线自己每次开跑前的例行对账: state 里的每个
# vultr 资源都按 ID 现查一次, 云上确实不存在的(404)从 state 移除, 之后 refresh
# 只会看到真实存在的资源。没有孤儿时它什么也不做, 因此可以无条件、重复执行。
#
# 刻意不做的事: 只删 state 记录, 不碰云上任何资源, 也不新建、不导入。把云上
# 存在但 state 里没有的实例"认领"进来是另一回事(见 adopt-resize-replacement),
# 需要人确认要认领哪一台, 不能由一个自动对账步骤替人决定。
# -----------------------------------------------------------------------------

: "${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE:?terraform workspace is required}"
: "${VULTR_API_KEY:?VULTR_API_KEY is required}"

terraform workspace select -or-create "${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE}"

# Read the backend state directly instead of `terraform show -json`.  `show`
# may emit a diagnostic instead of JSON when a provider cannot refresh a
# legacy object, which previously made jq treat a non-empty workspace as empty
# and allowed the later plan to hit the same 404.  A parse failure is unsafe:
# stop before changing either state or infrastructure.
state_json="$(terraform state pull)"
jq -e . >/dev/null <<<"${state_json}" || {
  echo "::error::Unable to parse Terraform state for ${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE}; refusing to reconcile state automatically." >&2
  exit 1
}

# `terraform state pull` 的输出是后端 state 格式, 资源在顶层 `resources[]`;
# `terraform show -json` 才是 `values.root_module`/`child_modules` 格式。这里
# 同时兼容两种格式, 否则脚本会误报 workspace 为空, 让后面的 refresh 再次
# 撞上已被 Vultr 删除的实例。
#
# root_module 及其所有 child_modules, 或 legacy resources[] 里的托管资源。
# data 源(mode=="data")不进 state 的删除范围: 它们每次 plan 重新求值, 没有
# 会陈旧的 ID。
entries=()
while IFS= read -r entry; do
  [[ -n "${entry}" ]] && entries+=("${entry}")
done < <(
  jq -r '
    def managed_vultr:
      select(.mode == "managed")
      | select(.type == "vultr_instance" or .type == "vultr_ssh_key");

    # `terraform show -json` nests module resources under child_modules. Walk
    # the module tree explicitly; a root-only query silently misses stale
    # instances in addresses such as module.compute_console_nat_onwalk_net.vultr_instance.this.
    def module_resources:
      (.resources[]?),
      (.child_modules[]? | module_resources);

    def modern_entries:
      [ (.values.root_module? // empty) | module_resources ]
      | map(managed_vultr)
      | .[] | [.address, .type, (.values.id // "")] | @tsv;

    # `terraform state pull` uses the legacy state shape. One resource object
    # can contain multiple instances, so preserve count/for_each index keys in
    # the address passed to `terraform state rm`.
    def legacy_address:
      ((.module // "") as $module
       | (if $module == "" then "" else ($module + ".") end)
       + .type + "." + .name);

    def legacy_index:
      if has("index_key") then
        if (.index_key | type) == "number"
        then "[" + (.index_key | tostring) + "]"
        else "[" + (.index_key | tojson) + "]"
        end
      else ""
      end;

    def legacy_entries:
      [ .resources[]? | managed_vultr as $resource
        | ($resource.instances[]? // {}) as $instance
        | [($resource | legacy_address) + ($instance | legacy_index), $resource.type,
           ($instance.attributes.id // "")] | @tsv
      ] | .[];

    if (.values.root_module? != null)
    then modern_entries
    else legacy_entries
    end
  ' <<<"${state_json}"
)

if [[ "${#entries[@]}" -eq 0 ]]; then
  echo "State reconcile: workspace ${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE} has no vultr resources in state; nothing to reconcile."
  exit 0
fi

# 404 -> 资源确实没了; 401/403 -> 凭据问题, 绝不能当成"没了"; 其它 -> 未知,
# 同样不能猜。误判一次就是把一台活着的机器从 state 里抹掉, 下一次 apply 会再
# 建一台重复的, 所以除 200/404 之外一律硬失败。
vultr_probe() {
  local url="$1" body="$2"
  local attempts=0 code=""
  while [[ ${attempts} -lt 5 ]]; do
    code="$(curl -sS --retry 3 --retry-delay 2 --retry-connrefused -o "${body}" -w '%{http_code}' \
      -H "Authorization: Bearer ${VULTR_API_KEY}" "${url}")"
    if [[ "${code}" =~ ^5[0-9]{2}$ ]]; then
      attempts=$((attempts + 1))
      sleep 2
      continue
    fi
    break
  done
  echo "${code}"
}

body="$(mktemp)"
trap 'rm -f "${body}"' EXIT

orphans=()
for entry in "${entries[@]}"; do
  IFS=$'\t' read -r address type id <<<"${entry}"

  if [[ -z "${id}" ]]; then
    echo "::error::${address} is in state without an id; refusing to guess whether it still exists." >&2
    exit 1
  fi

  case "${type}" in
    vultr_instance) url="https://api.vultr.com/v2/instances/${id}" ;;
    vultr_ssh_key)  url="https://api.vultr.com/v2/ssh-keys/${id}" ;;
    *)
      echo "::error::unsupported resource type for reconcile: ${type} (${address})" >&2
      exit 1 ;;
  esac

  http_code="$(vultr_probe "${url}" "${body}")"
  case "${http_code}" in
    200)
      echo "  ok      ${address} (${id})" ;;
    404)
      echo "::warning::${address} points at ${type} ${id}, which no longer exists on Vultr. Removing the stale state entry so refresh can proceed; the next apply will recreate it." >&2
      orphans+=("${address}") ;;
    401|403)
      echo "::error::Vultr API rejected the credential (HTTP ${http_code}) while probing ${address}. This is a credential problem — the state was left untouched." >&2
      head -c 400 "${body}" >&2
      exit 1 ;;
    *)
      echo "::error::Vultr API returned HTTP ${http_code} for ${address} (${id}); refusing to treat an unclear response as 'resource is gone'." >&2
      head -c 400 "${body}" >&2
      exit 1 ;;
  esac
done

if [[ "${#orphans[@]}" -eq 0 ]]; then
  echo "State reconcile: all ${#entries[@]} vultr resource(s) in state still exist on Vultr."
  exit 0
fi

# 改远端 state 之前留一份 runner 本地副本。backend 自己也有版本, 但这份副本
# 让"对账到一半失败"可以当场诊断, 而不必把 state 作为 artifact 暴露出去。
state_backup="${RUNNER_TEMP:-/tmp}/terraform-state-before-reconcile-${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE}.json"
printf '%s\n' "${state_json}" > "${state_backup}"

terraform state rm "${orphans[@]}"

echo "State reconcile: removed ${#orphans[@]} stale entr(ies): ${orphans[*]}"
{
  echo "### Terraform state reconcile"
  echo
  echo "Workspace \`${ENV_STEPS_ROUTE_OUTPUTS_TERRAFORM_WORKSPACE}\`: removed ${#orphans[@]} state entr(ies) whose Vultr resource returned 404."
  echo
  for address in "${orphans[@]}"; do
    echo "- \`${address}\`"
  done
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
