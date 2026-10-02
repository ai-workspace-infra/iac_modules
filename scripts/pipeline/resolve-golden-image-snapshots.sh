#!/usr/bin/env bash
set -euo pipefail

: "${VULTR_API_KEY:?VULTR_API_KEY is required}"

for command_name in curl jq; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "::error::Required command is not installed: ${command_name}" >&2
    exit 1
  fi
done

api_headers=(
  --header "Authorization: Bearer ${VULTR_API_KEY}"
  --header "Content-Type: application/json"
)

if ! snapshots_json="$(curl --silent --show-error --fail --compressed \
  --retry 3 --retry-delay 2 \
  "${api_headers[@]}" \
  'https://api.vultr.com/v2/snapshots?per_page=100')"; then
  if [[ "${TERRAFORM_ACTION:-apply}" != "plan" ]]; then
    echo "::error::Vultr Golden Image lookup failed; refusing to apply without resolving the requested image." >&2
    exit 1
  fi

  echo "::warning::Vultr Golden Image lookup failed during plan; using the declared OS fallback for this read-only plan." >&2
  snapshots_json='{"snapshots":[]}'
fi

resolve_snapshot() {
  local variable_name="$1"
  local description_prefix="$2"
  local requested_id="${!variable_name:-}"
  local requested_status=""

  if [[ -n "${requested_id}" ]]; then
    requested_status="$(curl --silent --show-error --fail --compressed \
      --retry 3 --retry-delay 2 \
      "${api_headers[@]}" \
      "https://api.vultr.com/v2/snapshots/${requested_id}" \
      | jq -r '.snapshot.status // empty' || true)"
    if [[ "${requested_status}" == "complete" ]]; then
      printf '%s\n' "${requested_id}"
      return 0
    fi
    echo "::warning::${variable_name}=${requested_id} is not a complete Vultr snapshot (${requested_status:-not found}); resolving the latest Golden Image instead." >&2
  fi

  jq -r --arg prefix "${description_prefix}" '
    [.snapshots[]?
      | select(.status == "complete")
      | select((.description // "") | startswith($prefix))]
    | sort_by(.date_created)
    | last
    | .id // empty
  ' <<<"${snapshots_json}"
}

write_env() {
  local variable_name="$1"
  local snapshot_id="$2"
  local env_file="${GITHUB_ENV:-/dev/stdout}"

  if [[ -n "${snapshot_id}" ]]; then
    echo "${variable_name}=${snapshot_id}" >>"${env_file}"
    echo "Resolved ${variable_name}=${snapshot_id}"
  else
    echo "::warning::No complete Golden Image found for ${variable_name}; Terraform will use the declared OS fallback." >&2
  fi
}

# The prefixes are emitted by artifacts/.github/scripts/packer-vultr-build.sh
# from the four Packer SOURCE_NAME values. UAT currently consumes the Debian
# variants; keeping the resolver name-based avoids hard-coding a snapshot UUID
# that the artifacts retention job may delete after the next image release.
write_env \
  SNAPSHOT_ID_DEBIAN13_WEBSAAS \
  "$(resolve_snapshot SNAPSHOT_ID_DEBIAN13_WEBSAAS 'golden-debian13_docker_compose_websaas-')"
write_env \
  SNAPSHOT_ID_DEBIAN13_AGENT_PROXY \
  "$(resolve_snapshot SNAPSHOT_ID_DEBIAN13_AGENT_PROXY 'golden-debian13_systemd_agent_proxy-')"
