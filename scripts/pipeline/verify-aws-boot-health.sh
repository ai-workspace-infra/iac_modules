#!/usr/bin/env bash
set -euo pipefail

: "${CMDB_FILE:?CMDB_FILE must point to the generated cmdb.json}"
: "${AWS_BOOT_HEALTH_TIMEOUT_SECONDS:=180}"
: "${AWS_BOOT_HEALTH_POLL_INTERVAL_SECONDS:=6}"
# First boot can take longer than one minute after both EC2 status checks pass,
# especially for fresh Debian ARM instances. Keep the check fail-closed, but
# allow enough time for cloud-init and sshd to finish before declaring failure.
: "${AWS_SSH_BANNER_TIMEOUT_SECONDS:=180}"
: "${AWS_SSH_BANNER_POLL_INTERVAL_SECONDS:=5}"

[[ -f "${CMDB_FILE}" ]] || {
  echo "::error::CMDB file not found: ${CMDB_FILE}" >&2
  exit 1
}

instances_file="$(mktemp)"
trap 'rm -f "${instances_file}"' EXIT
jq -r '
  to_entries[]
  | select((.value.instance_id // "") != "")
  | [
      (.value.name // .key),
      .value.instance_id,
      (.value.cloud_region // .value.region // ""),
      (.value.ip // ""),
      ((.value.ansible_port // 22) | tostring)
    ]
  | @tsv
' "${CMDB_FILE}" >"${instances_file}"

instance_count="$(wc -l <"${instances_file}" | tr -d ' ')"
if ((instance_count == 0)); then
  echo "::error::No AWS instance_id entries found in ${CMDB_FILE}." >&2
  exit 1
fi

show_console_output() {
  local name="$1" instance_id="$2" region="$3" output

  echo "::group::EC2 console output: ${name} (${instance_id}, ${region})"
  if output="$(aws ec2 get-console-output \
    --region "${region}" \
    --instance-id "${instance_id}" \
    --latest \
    --query Output \
    --output text 2>&1)"; then
    if [[ -z "${output}" || "${output}" == "None" ]]; then
      echo "No EC2 console output is available yet."
    else
      tail -n 200 <<<"${output}"
    fi
  else
    echo "Unable to read EC2 console output: ${output}" >&2
  fi
  echo "::endgroup::"
}

failed=0
while IFS=$'\t' read -r name instance_id region ip ssh_port; do
  if [[ -z "${region}" ]]; then
    echo "::error::${name} (${instance_id}) has no cloud_region or region in ${CMDB_FILE}." >&2
    failed=1
    continue
  fi

  deadline=$((SECONDS + AWS_BOOT_HEALTH_TIMEOUT_SECONDS))
  while true; do
    status="$(aws ec2 describe-instance-status \
      --region "${region}" \
      --instance-ids "${instance_id}" \
      --include-all-instances \
      --query 'InstanceStatuses[0].[InstanceState.Name,SystemStatus.Status,InstanceStatus.Status]' \
      --output text)"

    read -r state system_status instance_status <<<"${status:-None None None}"
    state="${state:-None}"
    system_status="${system_status:-None}"
    instance_status="${instance_status:-None}"
    echo "AWS boot health: ${name} instance=${instance_id} region=${region} state=${state} system=${system_status} instance=${instance_status}"

    if [[ "${state}" == "running" && "${system_status}" == "ok" && "${instance_status}" == "ok" ]]; then
      break
    fi

    if ((SECONDS >= deadline)); then
      echo "::error::${name} (${instance_id}, ${region}) did not pass both EC2 status checks within ${AWS_BOOT_HEALTH_TIMEOUT_SECONDS}s." >&2
      show_console_output "${name}" "${instance_id}" "${region}"
      failed=1
      break
    fi
    sleep "${AWS_BOOT_HEALTH_POLL_INTERVAL_SECONDS}"
  done

  if [[ "${state}" != "running" || "${system_status}" != "ok" || "${instance_status}" != "ok" ]]; then
    continue
  fi

  if [[ -z "${ip}" ]]; then
    echo "::error::${name} (${instance_id}) has no public IP in ${CMDB_FILE}." >&2
    show_console_output "${name}" "${instance_id}" "${region}"
    failed=1
    continue
  fi

  ssh_deadline=$((SECONDS + AWS_SSH_BANNER_TIMEOUT_SECONDS))
  while true; do
    if ssh_keys="$(ssh-keyscan -T 5 -p "${ssh_port}" "${ip}" 2>/dev/null)" && [[ -n "${ssh_keys}" ]]; then
      echo "AWS SSH readiness: ${name} instance=${instance_id} ip=${ip} port=${ssh_port} banner=ready"
      break
    fi

    if ((SECONDS >= ssh_deadline)); then
      echo "::error::${name} (${instance_id}, ${region}) did not return an SSH banner on ${ip}:${ssh_port} within ${AWS_SSH_BANNER_TIMEOUT_SECONDS}s." >&2
      show_console_output "${name}" "${instance_id}" "${region}"
      failed=1
      break
    fi
    sleep "${AWS_SSH_BANNER_POLL_INTERVAL_SECONDS}"
  done
done <"${instances_file}"

if ((failed != 0)); then
  exit 1
fi

echo "AWS boot health: all ${instance_count} instance(s) passed EC2 status and SSH banner checks."
