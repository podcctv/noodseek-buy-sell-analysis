#!/usr/bin/env bash
set -euo pipefail

SCRIPT_VERSION="1.0.0"
REPO_SLUG="${REPO_SLUG:-your-org/noodseek-buy-sell-analysis}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/noodseek-buy-sell-analysis}"
IMAGE_REPO_DEFAULT="ghcr.io/${REPO_SLUG,,}"
IMAGE_TAG_DEFAULT="latest"
RAW_BASE="https://raw.githubusercontent.com/${REPO_SLUG}/main/deploy"
SCRIPT_PATH="${SCRIPT_PATH:-}"

log() {
  echo "[nodeseek-installer] $*"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    log "缺少依赖: $cmd"
    exit 1
  fi
}

check_deps() {
  require_cmd curl
  require_cmd docker
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
  else
    log "未找到 docker compose（docker compose / docker-compose）"
    exit 1
  fi
}

self_upgrade() {
  if [[ -z "${SCRIPT_PATH}" ]]; then
    return 0
  fi

  local tmp latest
  tmp="$(mktemp)"
  if ! curl -fsSL "${RAW_BASE}/install.sh" -o "${tmp}"; then
    rm -f "${tmp}"
    log "跳过脚本自升级（无法下载远程 install.sh）"
    return 0
  fi

  latest="$(grep -E '^SCRIPT_VERSION=' "${tmp}" | head -n1 | cut -d'"' -f2)"
  if [[ -n "${latest}" && "${latest}" != "${SCRIPT_VERSION}" ]]; then
    log "检测到 install.sh 新版本 ${latest}（当前 ${SCRIPT_VERSION}），正在自升级..."
    cp "${tmp}" "${SCRIPT_PATH}"
    chmod +x "${SCRIPT_PATH}"
    rm -f "${tmp}"
    exec "${SCRIPT_PATH}" "$@"
  fi

  rm -f "${tmp}"
}

prepare_files() {
  mkdir -p "${INSTALL_DIR}/deploy" "${INSTALL_DIR}/data"
  curl -fsSL "${RAW_BASE}/docker-compose.yml" -o "${INSTALL_DIR}/deploy/docker-compose.yml"
}

write_env() {
  local image_repo image_tag web_port
  image_repo="${IMAGE_REPO:-$IMAGE_REPO_DEFAULT}"
  image_tag="${IMAGE_TAG:-$IMAGE_TAG_DEFAULT}"
  web_port="${WEB_PORT:-8080}"

  cat > "${INSTALL_DIR}/deploy/.env" <<EOT
IMAGE_REPO=${image_repo}
IMAGE_TAG=${image_tag}
WEB_PORT=${web_port}
EOT
}

pull_and_up() {
  local image_repo image_tag
  image_repo="${IMAGE_REPO:-$IMAGE_REPO_DEFAULT}"
  image_tag="${IMAGE_TAG:-$IMAGE_TAG_DEFAULT}"

  log "拉取镜像: ${image_repo}:${image_tag}"
  docker pull "${image_repo}:${image_tag}"

  log "启动服务"
  (cd "${INSTALL_DIR}/deploy" && "${COMPOSE_CMD[@]}" --env-file .env up -d)
}

print_next_steps() {
  local web_port
  web_port="${WEB_PORT:-8080}"
  cat <<EOT

安装完成 ✅
- 安装目录: ${INSTALL_DIR}
- 服务地址: http://127.0.0.1:${web_port}/admin/settings

后续升级：
  SCRIPT_PATH=${INSTALL_DIR}/deploy/install.sh REPO_SLUG=${REPO_SLUG} bash ${INSTALL_DIR}/deploy/install.sh
EOT
}

main() {
  check_deps
  self_upgrade "$@"
  prepare_files

  if [[ -n "${SCRIPT_PATH}" ]]; then
    cp "${SCRIPT_PATH}" "${INSTALL_DIR}/deploy/install.sh"
    chmod +x "${INSTALL_DIR}/deploy/install.sh"
  fi

  write_env
  pull_and_up
  print_next_steps
}

main "$@"
