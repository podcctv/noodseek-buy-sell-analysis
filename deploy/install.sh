#!/usr/bin/env bash
set -euo pipefail

SCRIPT_VERSION="2.0.0"
REPO_SLUG_DEFAULT="your-org/noodseek-buy-sell-analysis"
REPO_SLUG_RAW="${REPO_SLUG:-$REPO_SLUG_DEFAULT}"
REPO_SLUG="${REPO_SLUG_RAW#/}"
REPO_SLUG="${REPO_SLUG%/}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/noodseek-buy-sell-analysis}"
BRANCH="${BRANCH:-main}"
SCRIPT_PATH="${SCRIPT_PATH:-}"

log() {
  echo "[nodeseek-installer] $*"
}

if [[ -z "${REPO_SLUG}" ]]; then
  log "REPO_SLUG 不能为空（示例: your-org/noodseek-buy-sell-analysis）"
  exit 1
fi

REPO_URL="https://github.com/${REPO_SLUG}.git"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    log "缺少依赖: $cmd"
    exit 1
  fi
}

check_deps() {
  require_cmd git
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

sync_repo() {
  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    log "检测到已有安装，执行强制同步到 origin/${BRANCH}（覆盖 Git 文件）"
    git -C "${INSTALL_DIR}" fetch --depth=1 origin "${BRANCH}"
    git -C "${INSTALL_DIR}" reset --hard "origin/${BRANCH}"
    git -C "${INSTALL_DIR}" clean -fd
    return
  fi

  if [[ -d "${INSTALL_DIR}" ]] && [[ -n "$(find "${INSTALL_DIR}" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    log "目录 ${INSTALL_DIR} 已存在且非空，但不是 Git 仓库。请先备份后清空该目录再安装。"
    exit 1
  fi

  log "首次安装，克隆仓库: ${REPO_URL}"
  git clone --depth=1 --branch "${BRANCH}" "${REPO_URL}" "${INSTALL_DIR}"
}

ensure_env_file() {
  local env_file example_file
  env_file="${INSTALL_DIR}/deploy/.env"
  example_file="${INSTALL_DIR}/deploy/.env.example"

  if [[ -f "${env_file}" ]]; then
    log "保留现有配置: ${env_file}"
    return
  fi

  if [[ -f "${example_file}" ]]; then
    cp "${example_file}" "${env_file}"
    log "已生成本地配置文件: ${env_file}（请按需填写敏感信息）"
    return
  fi

  cat > "${env_file}" <<EOT
# Docker 镜像与端口
IMAGE_REPO=ghcr.io/${REPO_SLUG,,}
IMAGE_TAG=latest
WEB_PORT=8080

# 域名/服务地址（建议本地维护，不提交云端）
NDS_RSS_DOMAIN=https://rss.nodeseek.com/
NDS_CALLBACK_DOMAIN=

# AI 服务（敏感配置请仅保留在本机 .env）
NDS_AI_PROVIDER=openai_compatible
NDS_LLM_BASE_URL=
NDS_LLM_API_KEY=
NDS_LLM_MODEL=qwen3:4b
NDS_LLM_AUTH_MODE=none
NDS_LLM_CHAT_COMPLETIONS_PATH=/chat/completions
NDS_LLM_REQUEST_METHOD=POST
NDS_LLM_TIMEOUT_SECONDS=240
NDS_LLM_MAX_RETRIES=1
NDS_LLM_RETRY_DELAY_SECONDS=2
NDS_LLM_CUSTOM_HEADERS_JSON={"Content-Type":"application/json"}
EOT
  log "已生成默认配置: ${env_file}"
}

ensure_image_repo() {
  local env_file expected_image tmp_file current_image
  env_file="${INSTALL_DIR}/deploy/.env"
  expected_image="ghcr.io/${REPO_SLUG,,}"

  if [[ ! -f "${env_file}" ]]; then
    return
  fi

  current_image="$(awk -F'=' '/^IMAGE_REPO=/{print $2}' "${env_file}" | tail -n1)"
  if [[ -n "${current_image}" ]] && [[ "${current_image}" != "ghcr.io/owner/noodseek-buy-sell-analysis" ]]; then
    return
  fi

  tmp_file="$(mktemp)"
  awk -v image_repo="${expected_image}" '
    BEGIN { changed = 0 }
    /^IMAGE_REPO=/ {
      print "IMAGE_REPO=" image_repo
      changed = 1
      next
    }
    { print }
    END {
      if (!changed) {
        print "IMAGE_REPO=" image_repo
      }
    }
  ' "${env_file}" > "${tmp_file}"
  mv "${tmp_file}" "${env_file}"
  log "已将 IMAGE_REPO 设置为: ${expected_image}"
}

pull_and_up() {
  log "启动/更新服务容器"
  (cd "${INSTALL_DIR}/deploy" && "${COMPOSE_CMD[@]}" --env-file .env pull)
  (cd "${INSTALL_DIR}/deploy" && "${COMPOSE_CMD[@]}" --env-file .env up -d --remove-orphans)
}

print_next_steps() {
  local web_port
  web_port="$(awk -F'=' '/^WEB_PORT=/{print $2}' "${INSTALL_DIR}/deploy/.env" | tail -n1)"
  web_port="${web_port:-8080}"
  cat <<EOT

安装/升级完成 ✅
- 安装目录: ${INSTALL_DIR}
- 服务地址: http://127.0.0.1:${web_port}/admin/settings
- 本地配置文件: ${INSTALL_DIR}/deploy/.env

后续升级：
  REPO_SLUG=${REPO_SLUG} bash ${INSTALL_DIR}/deploy/update.sh
EOT
}

main() {
  check_deps
  sync_repo

  if [[ -n "${SCRIPT_PATH}" ]] && [[ -f "${SCRIPT_PATH}" ]]; then
    cp "${SCRIPT_PATH}" "${INSTALL_DIR}/deploy/install.sh"
    chmod +x "${INSTALL_DIR}/deploy/install.sh"
  fi

  ensure_env_file
  ensure_image_repo
  pull_and_up
  print_next_steps
}

main "$@"
