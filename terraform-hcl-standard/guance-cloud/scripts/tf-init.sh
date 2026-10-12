#!/usr/bin/env bash
# Initialise the unified S3-compatible state backend for a rendered Guance workdir.
set -euo pipefail
set +x
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workdir='' resources=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir) workdir="${2:?}"; shift 2 ;;
    --resources) resources="${2:?}"; shift 2 ;;
    *) printf 'Usage: tf-init.sh --workdir DIR --resources MANIFEST\n' >&2; exit 2 ;;
  esac
done
[[ -n "$workdir" && -n "$resources" ]] || { printf 'Usage: tf-init.sh --workdir DIR --resources MANIFEST\n' >&2; exit 2; }
# shellcheck source=tf-env.sh
source "$here/tf-env.sh" || exit 1
state_key="$(python3 "$here/generate.py" state-key --resources "$resources")"
printf 'State key: %s\n' "$state_key"
"${TERRAFORM:-terraform}" -chdir="$workdir" init -input=false -reconfigure -no-color \
  -backend-config="bucket=$TF_STATE_BUCKET" -backend-config="key=$state_key"
