#!/usr/bin/env bash
# setup-opentofu.sh: OpenTofu CLI + Silo S3 Remote State + Caddy HTTPS Installer
# Silo: S3-Compatible Object Storage. A MinIO fork maintained by PGSTY (https://github.com/pgsty/silo.git),
#       providing a self-hosted S3-compatible service to replace the unmaintained MinIO.
# Supports Debian 12+ and Ubuntu 22.04+ in Standalone and Team (Vault-injected) modes.

set -euo pipefail

# Pinned upstream versions
readonly OPENTOFU_VERSION="1.8.4"
# Self-hosted S3-Compatible Object Storage (pgsty/silo: A MinIO fork maintained by PGSTY to replace unmaintained MinIO)
readonly SILO_IMAGE="${SILO_IMAGE:-${MINIO_IMAGE:-pgsty/silo:RELEASE.2026-10-18T00-00-00Z}}"
readonly MINIO_IMAGE="${SILO_IMAGE}"
readonly CADDY_IMAGE="caddy:2.8.4-alpine"
readonly INSTALL_ROOT="/opt/opentofu-state"
readonly MINIO_BUCKET="opentofu-state"
readonly DEFAULT_REGION="main"

# Cryptographic SHA256 hashes for OpenTofu 1.8.4
readonly TOFU_SHA256_AMD64_DEB="b6ceb97b626964af57ceaa8b8ac33ea8ff3cb281e2eed3451dcb343e5bc0465a"
readonly TOFU_SHA256_ARM64_DEB="4aaefc75eb167ba42bc22472fffaee2d3d0e01b4962e9a09ec2506dda7ec378a"
readonly TOFU_SHA256_AMD64_TAR="d9bae67e876c9936165650a4e8c4e6d7e012c1f35cc9dd65f583e9d9382edf8f"
readonly TOFU_SHA256_ARM64_TAR="ae510170bf8733898980e10358956262c81a9ac4cfbc0d36388af63e27b56b1f"

# Defaults
DOMAIN=""
MODE=""
DRY_RUN=false
ACTION="install"
CREDENTIALS_GENERATED=false

usage() {
  cat <<'EOF'
Usage:
  setup-opentofu.sh --domain <fqdn> --standalone [options]
  setup-opentofu.sh --domain <fqdn> --with-state-backend [options]
  setup-opentofu.sh --uninstall
  setup-opentofu.sh --help

Deployment Modes:
  --standalone           Install OpenTofu CLI and standalone S3 remote state
                         backend with auto-generated credentials (printed once).
  --with-state-backend   Install OpenTofu CLI and team S3 remote state backend
                         using credentials injected via environment variables.

Required for Team Mode (--with-state-backend):
  TF_STATE_DOMAIN        FQDN for state backend (must match --domain)
  TF_STATE_ACCESS_KEY    S3 Access Key / Root User (Silo)
  TF_STATE_SECRET_KEY    S3 Secret Key / Root Password (Silo)

Options:
  --domain <fqdn>        Target domain for S3 endpoint and automatic TLS
  --dry-run              Validate configuration and print plan without executing
  --uninstall            Stop services and preserve data directory
  --help, -h             Show this help message
EOF
}

die() {
  printf '[setup-opentofu] ERROR: %s\n' "$*" >&2
  exit 1
}

warn() {
  printf '[setup-opentofu] WARN: %s\n' "$*" >&2
}

log() {
  printf '[setup-opentofu] INFO: %s\n' "$*"
}

check_root() {
  if [ "$(id -u)" -ne 0 ]; then
    die "This script must be run as root (uid 0). Please execute with sudo or as root."
  fi
}

check_os() {
  if [ ! -f /etc/os-release ]; then
    die "Cannot detect operating system: /etc/os-release not found."
  fi

  # shellcheck disable=SC1091
  . /etc/os-release

  local os_id="${ID:-}"
  local version_id="${VERSION_ID:-}"
  local major_version="${version_id%%.*}"

  case "$os_id" in
    debian)
      if [ -z "$major_version" ] || [ "$major_version" -lt 12 ]; then
        die "Unsupported OS: Debian ${version_id:-unknown}. Supported versions: Debian 12+."
      fi
      ;;
    ubuntu)
      if [ -z "$major_version" ] || [ "$major_version" -lt 22 ]; then
        die "Unsupported OS: Ubuntu ${version_id:-unknown}. Supported versions: Ubuntu 22.04+."
      fi
      ;;
    *)
      die "Unsupported OS: ${os_id:-unknown}. This script only supports Debian 12+ and Ubuntu 22.04+."
      ;;
  esac
}

validate_domain() {
  local domain="$1"
  if [[ ! "$domain" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$ ]]; then
    die "Invalid domain name: '$domain'. Must be a fully-qualified domain name (FQDN)."
  fi
}

detect_arch() {
  local machine
  machine="$(uname -m)"
  case "$machine" in
    x86_64|amd64)
      echo "amd64"
      ;;
    aarch64|arm64)
      echo "arm64"
      ;;
    *)
      die "Unsupported machine architecture: $machine. Supported: x86_64 (amd64), aarch64 (arm64)."
      ;;
  esac
}

check_dns_preflight() {
  local domain="$1"
  log "Performing DNS and TLS preflight check for '$domain'..."

  local resolved_ip=""
  if command -v getent >/dev/null 2>&1; then
    resolved_ip="$(getent ahosts "$domain" 2>/dev/null | awk '{print $1}' | head -n 1 || true)"
  fi
  if [ -z "$resolved_ip" ] && command -v dig >/dev/null 2>&1; then
    resolved_ip="$(dig +short A "$domain" 2>/dev/null | head -n 1 || true)"
  fi
  if [ -z "$resolved_ip" ] && command -v host >/dev/null 2>&1; then
    resolved_ip="$(host -t A "$domain" 2>/dev/null | awk '/has address/ {print $NF; exit}' || true)"
  fi
  if [ -z "$resolved_ip" ] && command -v python3 >/dev/null 2>&1; then
    resolved_ip="$(python3 -c "import socket; print(socket.gethostbyname('$domain'))" 2>/dev/null || true)"
  fi

  local public_ip=""
  if command -v curl >/dev/null 2>&1; then
    for ip_endpoint in "https://api.ipify.org" "https://icanhazip.com" "https://ifconfig.me"; do
      public_ip="$(curl -fsS --max-time 3 "$ip_endpoint" 2>/dev/null || true)"
      if [ -n "$public_ip" ]; then
        break
      fi
    done
  fi

  if [ -z "$resolved_ip" ]; then
    warn "DNS preflight: Domain '$domain' could not be resolved. Ensure an A record points to this server before issuing production TLS certs."
  elif [ -z "$public_ip" ]; then
    warn "DNS preflight: Domain '$domain' resolves to $resolved_ip, but host public IP could not be detected."
  elif [ "$resolved_ip" = "$public_ip" ]; then
    log "DNS preflight: Domain '$domain' points to host public IP ($public_ip). Preflight OK."
  else
    warn "DNS preflight: Domain '$domain' resolves to $resolved_ip, but host public IP is $public_ip. Caddy automatic HTTPS certificate issuance may fail until DNS propagates to this machine."
  fi
}

compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    return 1
  fi
}

install_docker_if_missing() {
  if command -v docker >/dev/null 2>&1 && compose_cmd version >/dev/null 2>&1; then
    log "Docker and Docker Compose are already installed."
    return 0
  fi

  log "Installing Docker and Docker Compose plugin..."
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    docker.io docker-compose-v2 || \
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    docker.io docker-compose || \
  die "Failed to install docker / docker compose from system repositories."

  systemctl enable --now docker || true
}

install_opentofu() {
  if command -v tofu >/dev/null 2>&1; then
    local installed_version
    installed_version="$(tofu version 2>/dev/null | head -n 1 || true)"
    if echo "$installed_version" | grep -q "OpenTofu v${OPENTOFU_VERSION}"; then
      log "OpenTofu CLI ${OPENTOFU_VERSION} is already installed, skipping."
      return 0
    fi
    log "OpenTofu CLI is installed ($installed_version), updating to ${OPENTOFU_VERSION}..."
  else
    log "Installing OpenTofu CLI version ${OPENTOFU_VERSION}..."
  fi

  local arch
  arch="$(detect_arch)"

  local tmp_dir
  tmp_dir="$(mktemp -d)"
  # shellcheck disable=SC2064
  trap "rm -rf '$tmp_dir'" RETURN

  local expected_deb_sha=""
  local expected_tar_sha=""
  local deb_filename="tofu_${OPENTOFU_VERSION}_${arch}.deb"
  local tar_filename="tofu_${OPENTOFU_VERSION}_linux_${arch}.tar.gz"
  local deb_url="https://github.com/opentofu/opentofu/releases/download/v${OPENTOFU_VERSION}/${deb_filename}"
  local tar_url="https://github.com/opentofu/opentofu/releases/download/v${OPENTOFU_VERSION}/${tar_filename}"

  if [ "$arch" = "amd64" ]; then
    expected_deb_sha="$TOFU_SHA256_AMD64_DEB"
    expected_tar_sha="$TOFU_SHA256_AMD64_TAR"
  else
    expected_deb_sha="$TOFU_SHA256_ARM64_DEB"
    expected_tar_sha="$TOFU_SHA256_ARM64_TAR"
  fi

  local install_success=false

  if command -v dpkg >/dev/null 2>&1; then
    log "Downloading OpenTofu ${OPENTOFU_VERSION} (.deb) for ${arch}..."
    if curl -fsSL "$deb_url" -o "${tmp_dir}/${deb_filename}"; then
      log "Verifying SHA256 checksum for ${deb_filename}..."
      local actual_sha
      actual_sha="$(sha256sum "${tmp_dir}/${deb_filename}" | awk '{print $1}')"
      if [ "$actual_sha" = "$expected_deb_sha" ]; then
        log "Checksum verified: ${actual_sha}"
        log "Installing OpenTofu package via dpkg..."
        if dpkg -i "${tmp_dir}/${deb_filename}" >/dev/null 2>&1 || (apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -f -y >/dev/null); then
          install_success=true
        fi
      else
        warn "SHA256 mismatch for ${deb_filename}, falling back to binary archive."
      fi
    fi
  fi

  if [ "$install_success" != true ]; then
    log "Downloading OpenTofu ${OPENTOFU_VERSION} (.tar.gz) for ${arch}..."
    if ! curl -fsSL "$tar_url" -o "${tmp_dir}/${tar_filename}"; then
      die "Failed to download OpenTofu archive from $tar_url"
    fi

    log "Verifying SHA256 checksum for ${tar_filename}..."
    local actual_tar_sha
    actual_tar_sha="$(sha256sum "${tmp_dir}/${tar_filename}" | awk '{print $1}')"
    if [ "$actual_tar_sha" != "$expected_tar_sha" ]; then
      die "SHA256 checksum mismatch for ${tar_filename}! Expected: $expected_tar_sha, Got: $actual_tar_sha"
    fi
    log "Checksum verified: ${actual_tar_sha}"

    tar -xzf "${tmp_dir}/${tar_filename}" -C "$tmp_dir"
    install -m 0755 "${tmp_dir}/tofu" /usr/local/bin/tofu
  fi

  if ! command -v tofu >/dev/null 2>&1; then
    die "OpenTofu installation failed: 'tofu' binary not found in PATH."
  fi

  local verified_version
  verified_version="$(tofu version | head -n 1)"
  log "OpenTofu installed successfully: ${verified_version}"
}

generate_backend_tf_content() {
  local domain="$1"
  cat <<EOF
# ==============================================================================
# OpenTofu S3 Remote State Backend Configuration
# ==============================================================================
# Endpoint: https://${domain}
# Bucket:   ${MINIO_BUCKET}
# Locking:  S3-native conditional write state locking (use_lockfile = true)
# ==============================================================================

terraform {
  backend "s3" {
    bucket                      = "${MINIO_BUCKET}"
    key                         = "terraform.tfstate"
    region                      = "${DEFAULT_REGION}"
    endpoints                   = {
      s3 = "https://${domain}"
    }
    endpoint                    = "https://${domain}"

    # Path-style access and native S3 state locking (.tflock file in MinIO)
    use_path_style              = true
    use_lockfile                = true

    # Compatibility flags for MinIO backend
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_s3_checksum            = true
  }
}

# Runtime credentials must be provided via environment variables:
#   export AWS_ACCESS_KEY_ID="<your-access-key>"
#   export AWS_SECRET_ACCESS_KEY="<your-secret-key>"
#   tofu init
EOF
}

generate_caddyfile_content() {
  local domain="$1"
  cat <<EOF
# Caddyfile: Automatic HTTPS Reverse Proxy for OpenTofu MinIO Backend
${domain} {
    encode gzip zstd

    reverse_proxy minio:9000 {
        header_up Host {host}
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }
}
EOF
}

generate_compose_content() {
  cat <<EOF
services:
  minio:
    image: ${MINIO_IMAGE}
    container_name: opentofu-minio
    restart: always
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: "\${MINIO_ROOT_USER}"
      MINIO_ROOT_PASSWORD: "\${MINIO_ROOT_PASSWORD}"
    volumes:
      - ${INSTALL_ROOT}/data:/data
    networks:
      - opentofu-net
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://localhost:9000/minio/health/live || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5

  caddy:
    image: ${CADDY_IMAGE}
    container_name: opentofu-caddy
    restart: always
    ports:
      - "80:80"
      - "443:443"
    environment:
      DOMAIN: "\${DOMAIN}"
    volumes:
      - ${INSTALL_ROOT}/Caddyfile:/etc/caddy/Caddyfile:ro
      - ${INSTALL_ROOT}/caddy_data:/data
      - ${INSTALL_ROOT}/caddy_config:/config
    networks:
      - opentofu-net
    depends_on:
      minio:
        condition: service_healthy

networks:
  opentofu-net:
    name: opentofu-net
    driver: bridge
EOF
}

backup_existing_config() {
  if [ -f "${INSTALL_ROOT}/docker-compose.yml" ] || [ -f "${INSTALL_ROOT}/Caddyfile" ]; then
    local backup_dir
    backup_dir="${INSTALL_ROOT}/backups/backup-$(date +%Y%m%d%H%M%S)"
    log "Existing configuration detected. Backing up to ${backup_dir}..."
    mkdir -p "$backup_dir"
    for file in docker-compose.yml Caddyfile .env backend.tf; do
      if [ -f "${INSTALL_ROOT}/${file}" ]; then
        cp -p "${INSTALL_ROOT}/${file}" "${backup_dir}/"
      fi
    done
  fi
}

resolve_credentials() {
  local mode="$1"
  local env_file="${INSTALL_ROOT}/.env"

  if [ "$mode" = "team" ]; then
    MINIO_ROOT_USER="$TF_STATE_ACCESS_KEY"
    MINIO_ROOT_PASSWORD="$TF_STATE_SECRET_KEY"
    CREDENTIALS_GENERATED=false
  elif [ "$mode" = "standalone" ]; then
    if [ -f "$env_file" ] && grep -q '^MINIO_ROOT_USER=' "$env_file" && grep -q '^MINIO_ROOT_PASSWORD=' "$env_file"; then
      log "Preserving existing credentials from ${env_file}."
      # shellcheck disable=SC1090
      MINIO_ROOT_USER="$(grep '^MINIO_ROOT_USER=' "$env_file" | cut -d= -f2-)"
      MINIO_ROOT_PASSWORD="$(grep '^MINIO_ROOT_PASSWORD=' "$env_file" | cut -d= -f2-)"
      CREDENTIALS_GENERATED=false
    else
      log "Generating strong credentials for standalone mode..."
      local random_suffix
      random_suffix="$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n' 2>/dev/null || openssl rand -hex 6 2>/dev/null || date +%s)"
      MINIO_ROOT_USER="tofuadmin_${random_suffix}"

      local raw_secret
      if command -v openssl >/dev/null 2>&1; then
        raw_secret="$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)"
      else
        raw_secret="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 32)"
      fi
      MINIO_ROOT_PASSWORD="${raw_secret}"
      CREDENTIALS_GENERATED=true
    fi
  fi
}

execute_dry_run() {
  local domain="$1"
  local mode="$2"

  check_dns_preflight "$domain"

  echo ""
  echo "================================================================================"
  echo " OpenTofu Remote State Installer - Dry Run Execution Plan"
  echo "================================================================================"
  echo "Target Domain:          ${domain}"
  echo "Deployment Mode:        ${mode}"
  echo "Install Directory:      ${INSTALL_ROOT}"
  echo ""
  echo "Upstream Components (Pinned):"
  echo "  - OpenTofu CLI:       v${OPENTOFU_VERSION}"
  echo "  - S3 Remote Backend:  ${SILO_IMAGE} (pgsty/silo: S3-Compatible Object Storage. A MinIO fork maintained by PGSTY)"
  echo "  - Caddy Proxy:        ${CADDY_IMAGE}"
  echo ""
  echo "Planned Directory Layout:"
  echo "  ${INSTALL_ROOT}/"
  echo "  ├── docker-compose.yml"
  echo "  ├── Caddyfile"
  echo "  ├── .env                (mode 0600)"
  echo "  ├── backend.tf"
  echo "  ├── data/opentofu-state (Silo S3 remote state bucket)"
  echo "  ├── caddy_data/         (automatic TLS certs)"
  echo "  └── caddy_config/"
  echo ""
  echo "File Preview: backend.tf"
  echo "--------------------------------------------------------------------------------"
  generate_backend_tf_content "$domain"
  echo "--------------------------------------------------------------------------------"
  echo ""
  echo "Dry run completed successfully. No changes were made to the system."
  echo "================================================================================"
}

execute_uninstall() {
  log "Executing uninstall..."

  if [ -d "$INSTALL_ROOT" ] && [ -f "${INSTALL_ROOT}/docker-compose.yml" ]; then
    if command -v docker >/dev/null 2>&1 && compose_cmd version >/dev/null 2>&1; then
      log "Stopping and removing MinIO and Caddy containers..."
      compose_cmd -f "${INSTALL_ROOT}/docker-compose.yml" down || true
    fi
  fi

  echo ""
  echo "================================================================================"
  echo "🛑 OpenTofu & Remote State Uninstalled"
  echo "================================================================================"
  echo "Services have been stopped and removed."
  echo ""
  echo "Persistent data and state files have been safely PRESERVED at:"
  echo "  ${INSTALL_ROOT}/data"
  echo "Configuration files preserved at:"
  echo "  ${INSTALL_ROOT}"
  echo ""
  echo "To permanently wipe all remote state and configurations, run:"
  echo "  rm -rf ${INSTALL_ROOT}"
  echo "================================================================================"
}

# ------------------------------------------------------------------------------
# Argument Parsing
# ------------------------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --domain)
      [ $# -lt 2 ] && die "Option --domain requires an argument."
      DOMAIN="$2"
      shift 2
      ;;
    --domain=*)
      DOMAIN="${1#*=}"
      shift
      ;;
    --standalone)
      [ -n "$MODE" ] && [ "$MODE" != "standalone" ] && die "Cannot specify both --standalone and --with-state-backend."
      MODE="standalone"
      shift
      ;;
    --with-state-backend)
      [ -n "$MODE" ] && [ "$MODE" != "team" ] && die "Cannot specify both --standalone and --with-state-backend."
      MODE="team"
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --uninstall)
      ACTION="uninstall"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: '$1'. Run with --help for usage."
      ;;
  esac
done

# Check root and OS for operational actions
check_root
check_os

if [ "$ACTION" = "uninstall" ]; then
  execute_uninstall
  exit 0
fi

# Validate parameters for install action
[ -z "$DOMAIN" ] && die "Option --domain <fqdn> is required."
validate_domain "$DOMAIN"
[ -z "$MODE" ] && die "Must specify either --standalone or --with-state-backend mode."

# Fail-closed check for team mode environment variables
if [ "$MODE" = "team" ]; then
  missing_vars=()
  [ -z "${TF_STATE_DOMAIN:-}" ] && missing_vars+=("TF_STATE_DOMAIN")
  [ -z "${TF_STATE_ACCESS_KEY:-}" ] && missing_vars+=("TF_STATE_ACCESS_KEY")
  [ -z "${TF_STATE_SECRET_KEY:-}" ] && missing_vars+=("TF_STATE_SECRET_KEY")

  if [ "${#missing_vars[@]}" -gt 0 ]; then
    die "Team mode (--with-state-backend) requires environment variables: ${missing_vars[*]}. All must be non-empty."
  fi

  if [ "$TF_STATE_DOMAIN" != "$DOMAIN" ]; then
    die "Mismatch: --domain ($DOMAIN) does not match TF_STATE_DOMAIN ($TF_STATE_DOMAIN)."
  fi
fi

if [ "$DRY_RUN" = true ]; then
  execute_dry_run "$DOMAIN" "$MODE"
  exit 0
fi

# ------------------------------------------------------------------------------
# Live Execution
# ------------------------------------------------------------------------------
check_dns_preflight "$DOMAIN"

# 1. OpenTofu CLI
install_opentofu

# 2. Docker & Compose
install_docker_if_missing

# 3. Directories & state bucket
log "Preparing directories in ${INSTALL_ROOT}..."
mkdir -p "${INSTALL_ROOT}"
mkdir -p "${INSTALL_ROOT}/data/${MINIO_BUCKET}"
mkdir -p "${INSTALL_ROOT}/caddy_data"
mkdir -p "${INSTALL_ROOT}/caddy_config"
chmod 700 "${INSTALL_ROOT}"

# 4. Backup existing config if any
backup_existing_config

# 5. Resolve credentials
resolve_credentials "$MODE"

# 6. Write configuration files
log "Writing Caddyfile..."
generate_caddyfile_content "$DOMAIN" > "${INSTALL_ROOT}/Caddyfile"
chmod 644 "${INSTALL_ROOT}/Caddyfile"

log "Writing docker-compose.yml..."
generate_compose_content > "${INSTALL_ROOT}/docker-compose.yml"
chmod 644 "${INSTALL_ROOT}/docker-compose.yml"

log "Writing backend.tf template..."
generate_backend_tf_content "$DOMAIN" > "${INSTALL_ROOT}/backend.tf"
chmod 644 "${INSTALL_ROOT}/backend.tf"

log "Writing environment file (.env)..."
cat > "${INSTALL_ROOT}/.env" <<EOF
DOMAIN=${DOMAIN}
MINIO_ROOT_USER=${MINIO_ROOT_USER}
MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}
EOF
chmod 600 "${INSTALL_ROOT}/.env"

# 7. Start containers
log "Deploying MinIO and Caddy services via Docker Compose..."
compose_cmd -f "${INSTALL_ROOT}/docker-compose.yml" up -d

# 8. Service health check
log "Waiting for MinIO service to report healthy..."
health_ok=false
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:9000/minio/health/live >/dev/null 2>&1; then
    health_ok=true
    break
  fi
  sleep 1
done

if [ "$health_ok" != true ]; then
  warn "MinIO health check timed out on http://127.0.0.1:9000/minio/health/live. Check logs with 'docker compose -f ${INSTALL_ROOT}/docker-compose.yml logs minio'."
fi

# 9. Health & Completion Summary
tofu_v="$(tofu version 2>/dev/null | head -n 1 || echo "OpenTofu v${OPENTOFU_VERSION}")"

echo ""
echo "================================================================================"
if [ "$MODE" = "standalone" ]; then
  echo "🎉 OpenTofu & Remote State Setup Completed (Standalone Mode)"
else
  echo "🎉 OpenTofu & Remote State Setup Completed (Team Mode)"
fi
echo "================================================================================"
echo "Status:             $([ "$health_ok" = true ] && echo "HEALTHY" || echo "STARTING")"
echo "Public S3 Endpoint: https://${DOMAIN}"
echo "Local S3 Endpoint:  http://127.0.0.1:9000"
echo "OpenTofu Version:   ${tofu_v}"
echo "S3 Storage Health:  $([ "$health_ok" = true ] && echo "OK (live)" || echo "PENDING")"
echo "Install Root:       ${INSTALL_ROOT}"
echo "Bucket Name:        ${MINIO_BUCKET}"
echo ""

if [ "$MODE" = "standalone" ]; then
  if [ "$CREDENTIALS_GENERATED" = true ]; then
    echo "Generated S3 Credentials (Silo - save these immediately!):"
    echo "  Access Key:       ${MINIO_ROOT_USER}"
    echo "  Secret Key:       ${MINIO_ROOT_PASSWORD}"
    echo ""
    echo "⚠️  SECURITY NOTICE:"
    echo "  These credentials have been saved to ${INSTALL_ROOT}/.env (mode 0600)."
    echo "  They will NOT be displayed again. For production usage, store them in Vault:"
    echo "    vault kv put secret/cicd/iac_state \\"
    echo "      domain=\"https://${DOMAIN}\" \\"
    echo "      access_key=\"${MINIO_ROOT_USER}\" \\"
    echo "      secret_key=\"${MINIO_ROOT_PASSWORD}\""
    echo ""
  else
    echo "S3 Credentials (Silo):"
    echo "  Existing credentials preserved from ${INSTALL_ROOT}/.env"
    echo ""
  fi
fi

if [ "$MODE" = "team" ]; then
  echo "Remote State Backend Template:"
  echo "  Saved to: ${INSTALL_ROOT}/backend.tf"
  echo ""
  echo "Usage Instructions:"
  echo "  1. Copy backend.tf into your OpenTofu project directory."
  echo "  2. Inject your runtime credentials into environment variables:"
  echo "       export AWS_ACCESS_KEY_ID=\"\$TF_STATE_ACCESS_KEY\""
  echo "       export AWS_SECRET_ACCESS_KEY=\"\$TF_STATE_SECRET_KEY\""
  echo "  3. Initialize OpenTofu:"
  echo "       tofu init"
  echo ""
fi
echo "================================================================================"
