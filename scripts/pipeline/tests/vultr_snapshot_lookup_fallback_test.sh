#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
resolver="${repo_root}/scripts/pipeline/resolve-golden-image-snapshots.sh"
test_root="$(mktemp -d)"
trap 'rm -rf "${test_root}"' EXIT

mkdir -p "${test_root}/bin"
cat >"${test_root}/bin/curl" <<'MOCK_CURL'
#!/usr/bin/env bash
echo "mock Vultr API unavailable" >&2
exit 22
MOCK_CURL
chmod +x "${test_root}/bin/curl"

if ! output="$(PATH="${test_root}/bin:${PATH}" \
  VULTR_API_KEY=test-only-key \
  TERRAFORM_ACTION=plan \
  GITHUB_ENV="${test_root}/plan.env" \
  bash "${resolver}" 2>&1)"; then
  echo "Read-only plan should fall back when Vultr is unavailable:" >&2
  printf '%s\n' "${output}" >&2
  exit 1
fi

grep -Fq 'using the declared OS fallback for this read-only plan' <<<"${output}"
[[ ! -s "${test_root}/plan.env" ]]

if PATH="${test_root}/bin:${PATH}" \
  VULTR_API_KEY=test-only-key \
  TERRAFORM_ACTION=apply \
  GITHUB_ENV="${test_root}/apply.env" \
  bash "${resolver}" >"${test_root}/apply.log" 2>&1; then
  echo "Apply must fail closed when Vultr image lookup is unavailable" >&2
  exit 1
fi

grep -Fq 'refusing to apply without resolving the requested image' "${test_root}/apply.log"
[[ ! -s "${test_root}/apply.env" ]]

echo "vultr_snapshot_lookup_fallback_test: PASS"
