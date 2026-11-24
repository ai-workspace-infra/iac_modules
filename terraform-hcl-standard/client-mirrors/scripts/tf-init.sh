#!/usr/bin/env bash
# Initialise the unified S3-compatible state backend for a rendered client-mirrors workdir.
set -euo pipefail
set +x

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workdir='' resources='' stack=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir) workdir="${2:?}"; shift 2 ;;
    --resources|--manifest) resources="${2:?}"; shift 2 ;;
    --stack) stack="${2:?}"; shift 2 ;;
    *) printf 'Usage: tf-init.sh [--workdir DIR] [--resources MANIFEST | --manifest MANIFEST | --stack mirrors|repos]\n' >&2; exit 2 ;;
  esac
done

gen_args=()
if [[ -n "$resources" ]]; then
  gen_args+=(--manifest "$resources")
fi
if [[ -n "$stack" ]]; then
  gen_args+=(--stack "$stack")
fi
if [[ ${#gen_args[@]} -eq 0 ]]; then
  printf 'Usage: tf-init.sh [--workdir DIR] [--resources MANIFEST | --manifest MANIFEST | --stack mirrors|repos]\n' >&2
  exit 2
fi
if [[ -z "$workdir" ]]; then
  if [[ "$stack" == "repos" ]]; then
    workdir="$here/../envs/svc-plus-prod-repos"
  else
    workdir="$here/../envs/svc-plus-prod"
  fi
fi

# shellcheck source-path=SCRIPTDIR source=tf-env.sh
source "$here/tf-env.sh" || exit 1
state_key="$(python3 "$here/generate.py" state-key "${gen_args[@]}")"
printf 'State key: %s\n' "$state_key"
"${TERRAFORM:-terraform}" -chdir="$workdir" init -input=false -reconfigure -no-color \
  -backend-config="bucket=$TF_STATE_BUCKET" \
  -backend-config="key=$state_key"
