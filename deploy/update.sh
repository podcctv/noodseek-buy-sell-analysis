#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/noodseek-buy-sell-analysis}"
REPO_SLUG="${REPO_SLUG:-your-org/noodseek-buy-sell-analysis}"

if [[ -x "${INSTALL_DIR}/deploy/install.sh" ]]; then
  SCRIPT_PATH="${INSTALL_DIR}/deploy/install.sh" REPO_SLUG="${REPO_SLUG}" bash "${INSTALL_DIR}/deploy/install.sh"
  exit 0
fi

echo "未找到本地 install.sh，改为在线下载安装并执行。"
TMP_SCRIPT="$(mktemp)"
curl -fsSL "https://raw.githubusercontent.com/${REPO_SLUG}/main/deploy/install.sh" -o "${TMP_SCRIPT}"
chmod +x "${TMP_SCRIPT}"
SCRIPT_PATH="${TMP_SCRIPT}" REPO_SLUG="${REPO_SLUG}" INSTALL_DIR="${INSTALL_DIR}" bash "${TMP_SCRIPT}"
rm -f "${TMP_SCRIPT}"
