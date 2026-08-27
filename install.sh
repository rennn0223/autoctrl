#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${AUTOCTRL_REPO_URL:-https://github.com/rennn0223/autoctrl.git}"
REPO_REF="${AUTOCTRL_REF:-main}"
INSTALL_DIR="${AUTOCTRL_INSTALL_DIR:-${HOME}/autoctrl}"
BIN_DIR="${AUTOCTRL_BIN_DIR:-${HOME}/.local/bin}"
ROS_SETUP="${AUTOCTRL_ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
UV_INSTALL_URL="${AUTOCTRL_UV_INSTALL_URL:-https://astral.sh/uv/install.sh}"

say() {
  printf '• %s\n' "$1"
}

fail() {
  printf 'AutoCtrl 安裝失敗：%s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "找不到 $1 指令"
}

require_command curl
require_command git
[[ -f "$ROS_SETUP" ]] || fail "找不到 ROS2 環境：$ROS_SETUP"

if ! command -v uv >/dev/null 2>&1; then
  say "安裝 uv（官方安裝器：$UV_INSTALL_URL）"
  uv_installer="$(mktemp)"
  curl -fsSL "$UV_INSTALL_URL" -o "$uv_installer"
  sh "$uv_installer"
  rm -f "$uv_installer"
  export PATH="${HOME}/.local/bin:${PATH}"
fi
require_command uv

if [[ -d "$INSTALL_DIR/.git" ]]; then
  if [[ -n "$(git -C "$INSTALL_DIR" status --porcelain)" ]]; then
    fail "$INSTALL_DIR 有尚未提交的修改；為避免覆寫，已停止更新"
  fi
  say "更新 AutoCtrl：$INSTALL_DIR"
  git -C "$INSTALL_DIR" pull --ff-only origin "$REPO_REF"
elif [[ -e "$INSTALL_DIR" ]] && [[ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
  fail "$INSTALL_DIR 已存在且不是 AutoCtrl Git repository"
else
  install_parent="$(dirname -- "$INSTALL_DIR")"
  mkdir -p "$install_parent"
  say "下載 AutoCtrl：$REPO_URL@$REPO_REF"
  git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$INSTALL_DIR"
fi

say "建立 uv 隔離環境"
AUTOCTRL_ROS_SETUP="$ROS_SETUP" "$INSTALL_DIR/scripts/bootstrap"

mkdir -p "$BIN_DIR"
ln -sfn "$INSTALL_DIR/scripts/start-dgx" "$BIN_DIR/autoctrl"

say "安裝完成：$INSTALL_DIR"
printf '啟動指令：%s/autoctrl\n' "$BIN_DIR"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) printf '請將下列內容加入 shell 設定：export PATH="%s:$PATH"\n' "$BIN_DIR" ;;
esac

if ! command -v docker >/dev/null 2>&1; then
  printf '提醒：尚未找到 Docker；Zenoh bridge 必須另外準備。\n' >&2
fi
if ! command -v ollama >/dev/null 2>&1; then
  printf '提醒：尚未找到 Ollama；請先安裝並準備 qwen3.6:35b。\n' >&2
fi

printf '\n重要：此安裝器不會設定 ROS2／Zenoh 端到端通訊。\n'
printf '請自行設定 DGX 與機器人兩端的 ROS2 環境、Zenoh bridge、domain、路由與 topic 規則。\n'
printf '機器人 namespace 預設為 /small，但可透過 robot_namespace 參數更換；兩端設定必須一致。\n'
printf '/doctor 的 Zenoh 檢查只代表 DGX 本機容器正在執行，不代表遠端 topics 已經打通。\n'
printf '完整說明：%s/docs/SETUP.md\n' "$INSTALL_DIR"
