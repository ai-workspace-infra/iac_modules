#!/usr/bin/env bash
set -euo pipefail

# Web SaaS Full Stack installer orchestrator.
# Mandatory Core Services: portal, accounts, postgresql.

MODULES_RAW=""
DOMAIN=""
MODE="docker"
RELEASE=""
MODULE_SOURCE="${WEB_SAAS_MODULE_SOURCE:-https://install.svc.plus/web-saas/releases}"
INSTALL_ROOT="/etc/web-saas"
DRY_RUN=false
ASSUME_YES=false

readonly CORE_MODULES=(portal accounts postgresql)
readonly OPTIONAL_MODULES=(proxy xconnect-zero open-platform ai-aggregator)
readonly ORDERED_MODULES=(postgresql accounts portal open-platform proxy xconnect-zero ai-aggregator)

usage() {
  cat <<'EOF'
Usage:
  install.sh --domain <domain> --modules <csv> --release <version> [options]

Core services, always installed:
  portal accounts postgresql

Optional modules:
  proxy xconnect-zero open-platform ai-aggregator all

Options:
  --modules <csv>          Optional modules; use all for the full stack
  --domain <domain>        Primary domain; required
  --mode <docker|k8s>      Deployment mode; default: docker
  --release <version>      Immutable release version; required for execution
  --module-source <url>    Release root; default: install.svc.plus
  --install-root <path>    State/config directory; default: /etc/web-saas
  --dry-run                Print the resolved plan without downloading/executing
  --yes                    Skip the execution confirmation
  --help                   Show this help
EOF
}

die() {
  printf '[web-saas] error: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[web-saas] %s\n' "$*"
}

contains() {
  local needle="$1"
  shift
  local item
  for item in "$@"; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

add_unique() {
  local item="$1"
  if ! contains "$item" "${RESOLVED_MODULES[@]}" 2>/dev/null; then
    RESOLVED_MODULES+=("$item")
  fi
}

resolve_modules() {
  local requested module
  RESOLVED_MODULES=()

  # Core Services are mandatory and cannot be disabled by --modules.
  for module in "${CORE_MODULES[@]}"; do
    add_unique "$module"
  done

  if [[ -n "$MODULES_RAW" ]]; then
    local requested_modules=()
    IFS=',' read -r -a requested_modules <<< "$MODULES_RAW"
    for requested in "${requested_modules[@]}"; do
      if [[ "$requested" == "all" ]]; then
        for module in "${OPTIONAL_MODULES[@]}"; do
          add_unique "$module"
        done
      elif contains "$requested" "${OPTIONAL_MODULES[@]}"; then
        add_unique "$requested"
      elif [[ "$requested" != "core" && -n "$requested" ]]; then
        die "unknown module: $requested"
      fi
    done
  fi

  # Dependency closure for optional control planes.
  if contains xconnect-zero "${RESOLVED_MODULES[@]}"; then
    add_unique proxy
  fi
  if contains ai-aggregator "${RESOLVED_MODULES[@]}"; then
    add_unique open-platform
  fi

  local ordered=()
  for module in "${ORDERED_MODULES[@]}"; do
    if contains "$module" "${RESOLVED_MODULES[@]}"; then
      ordered+=("$module")
    fi
  done
  RESOLVED_MODULES=("${ordered[@]}")
}

preflight() {
  command -v curl >/dev/null 2>&1 || die "curl is required"
  command -v uname >/dev/null 2>&1 || die "uname is required"
  [[ -n "$DOMAIN" ]] || die "--domain is required"
  [[ "$DOMAIN" != */* && "$DOMAIN" != *:* && "$DOMAIN" != *' '* ]] || die "invalid domain"
  [[ "$MODE" == docker || "$MODE" == k8s ]] || die "unsupported mode: $MODE"

  if [[ "$DRY_RUN" == false ]]; then
    [[ -n "$RELEASE" ]] || die "--release is required unless --dry-run is used"
    [[ "$RELEASE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "release must use vMAJOR.MINOR.PATCH"
    [[ "$(uname -s)" == Linux ]] || die "execution requires Linux"
    [[ "$(id -u)" -eq 0 ]] || die "execution requires root; use --dry-run for an unprivileged plan"
    if [[ "$MODE" == docker ]]; then
      command -v docker >/dev/null 2>&1 || die "docker is required for --mode docker"
    else
      command -v kubectl >/dev/null 2>&1 || die "kubectl is required for --mode k8s"
      command -v helm >/dev/null 2>&1 || die "helm is required for --mode k8s"
    fi
  fi
}

print_plan() {
  log "host=$(uname -s)/$(uname -m)"
  log "domain=$DOMAIN"
  log "mode=$MODE"
  log "release=${RELEASE:-<not set; dry-run only>}"
  log "module-source=$MODULE_SOURCE"
  log "install-root=$INSTALL_ROOT"
  log "resolved modules: ${RESOLVED_MODULES[*]}"
}

sha256_file() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  else
    die "sha256sum or shasum is required"
  fi
}

verify_module() {
  local sums="$1"
  local module_file="$2"
  local filename expected actual
  filename="$(basename "$module_file")"
  expected="$(awk -v name="$filename" '$2 == name { print $1; exit }' "$sums")"
  [[ -n "$expected" ]] || die "missing checksum for $filename"
  actual="$(sha256_file "$module_file")"
  [[ "$actual" == "$expected" ]] || die "checksum mismatch for $filename"
}

fetch_module() {
  local module="$1"
  local release_dir="$2"
  local target="$3"
  local source_file="$MODULE_SOURCE/$RELEASE/$module.sh"

  if [[ -d "$MODULE_SOURCE" ]]; then
    source_file="$MODULE_SOURCE/$module.sh"
    [[ -f "$source_file" ]] || die "local module not found: $source_file"
    cp "$source_file" "$target"
  else
    curl --fail --silent --show-error --location --retry 3 \
      --connect-timeout 10 --output "$target" "$source_file"
  fi

  verify_module "$release_dir/SHA256SUMS" "$target"
  chmod 0755 "$target"
}

run_install() {
  local work_dir release_dir module module_file
  work_dir="$(mktemp -d "${TMPDIR:-/tmp}/web-saas-install.XXXXXX")"
  trap 'rm -rf -- '"$(printf '%q' "$work_dir")" EXIT
  release_dir="$work_dir/release"
  mkdir -p "$release_dir"

  if [[ -d "$MODULE_SOURCE" ]]; then
    cp "$MODULE_SOURCE/SHA256SUMS" "$release_dir/SHA256SUMS"
  else
    curl --fail --silent --show-error --location --retry 3 \
      --connect-timeout 10 --output "$release_dir/SHA256SUMS" \
      "$MODULE_SOURCE/$RELEASE/SHA256SUMS"
  fi

  # Verify the complete selected release before any module changes the host.
  for module in "${RESOLVED_MODULES[@]}"; do
    log "fetching and verifying module: $module"
    fetch_module "$module" "$release_dir" "$work_dir/$module.sh"
    bash -n "$work_dir/$module.sh"
  done

  umask 077
  mkdir -p "$INSTALL_ROOT/state"
  printf '%s\n' "${RESOLVED_MODULES[@]}" > "$INSTALL_ROOT/state/modules"
  printf 'domain=%s\nmode=%s\nrelease=%s\n' "$DOMAIN" "$MODE" "$RELEASE" \
    > "$INSTALL_ROOT/state/install.env"

  for module in "${RESOLVED_MODULES[@]}"; do
    module_file="$work_dir/$module.sh"
    log "executing module: $module"
    bash "$module_file" \
      --domain "$DOMAIN" \
      --mode "$MODE" \
      --release "$RELEASE" \
      --install-root "$INSTALL_ROOT" \
      --yes
  done
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --modules|--module) MODULES_RAW="${2:-}"; shift 2 ;;
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    --release) RELEASE="${2:-}"; shift 2 ;;
    --module-source) MODULE_SOURCE="${2:-}"; shift 2 ;;
    --install-root) INSTALL_ROOT="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --yes) ASSUME_YES=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

resolve_modules
preflight
print_plan

if [[ "$DRY_RUN" == true ]]; then
  log "dry-run complete; no files downloaded and no services changed"
  exit 0
fi

if [[ "$ASSUME_YES" == false ]]; then
  [[ -t 0 ]] || die "non-interactive execution requires --yes"
  printf '[web-saas] continue with the plan above? [y/N] '
  read -r answer
  [[ "$answer" == y || "$answer" == Y ]] || die "installation cancelled"
fi

run_install
log "module installation completed; run the acceptance checks from the installation plan"
