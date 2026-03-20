#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"

pick_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return
  fi
  echo ""
}

normalize_proxy_url() {
  local value="$1"
  if [[ "$value" == socks://* ]]; then
    printf 'socks5://%s' "${value#socks://}"
    return
  fi
  printf '%s' "$value"
}

ensure_proxy_env() {
  local has_proxy=""
  for name in ALL_PROXY all_proxy HTTPS_PROXY https_proxy HTTP_PROXY http_proxy; do
    if [[ -n "${!name:-}" ]]; then
      has_proxy="yes"
      break
    fi
  done

  if [[ -z "$has_proxy" ]]; then
    local auto_proxy_port=""
    local candidate_ports=(7897 7890 1080)
    for port in "${candidate_ports[@]}"; do
      if command -v python3 >/dev/null 2>&1; then
        if python3 -c "import socket; s=socket.socket(); s.settimeout(0.2); ok=(s.connect_ex(('127.0.0.1', $port))==0); s.close(); raise SystemExit(0 if ok else 1)" >/dev/null 2>&1; then
          auto_proxy_port="$port"
          break
        fi
      elif command -v python >/dev/null 2>&1; then
        if python -c "import socket; s=socket.socket(); s.settimeout(0.2); ok=(s.connect_ex(('127.0.0.1', $port))==0); s.close(); raise SystemExit(0 if ok else 1)" >/dev/null 2>&1; then
          auto_proxy_port="$port"
          break
        fi
      fi
    done

    if [[ -n "$auto_proxy_port" ]]; then
      export HTTP_PROXY="http://127.0.0.1:${auto_proxy_port}/"
      export http_proxy="$HTTP_PROXY"
      export HTTPS_PROXY="$HTTP_PROXY"
      export https_proxy="$HTTP_PROXY"
      export ALL_PROXY="socks5://127.0.0.1:${auto_proxy_port}/"
      export all_proxy="$ALL_PROXY"
      echo "[INFO] 未检测到代理环境，已自动接管本地代理端口 ${auto_proxy_port}。"
    fi
  fi

  for name in ALL_PROXY all_proxy HTTPS_PROXY https_proxy HTTP_PROXY http_proxy; do
    if [[ -n "${!name:-}" ]]; then
      export "$name=$(normalize_proxy_url "${!name}")"
    fi
  done
}

echo "=========================================="
echo "  声文智汇 (ShengWen) - 一键启动"
echo "=========================================="
echo

if [[ -f "${VENV_DIR}/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${VENV_DIR}/bin/activate"
else
  echo "[WARN] 未检测到 ${VENV_DIR}，将使用系统 Python。"
  echo "[WARN] 建议先执行 ./deploy一键部署.sh 完成依赖安装。"
fi

ensure_proxy_env

PYTHON_CMD="$(pick_python)"
if [[ -z "$PYTHON_CMD" ]]; then
  echo "[ERROR] 未找到 Python，请先安装 Python 3.10+。"
  exit 1
fi

# ---------- 前端自动构建 ----------
# 检测前端源码是否比 dist/ 更新，如果有变化则自动 rebuild
frontend_needs_build() {
  # 如果 dist 目录不存在，肯定需要构建
  if [[ ! -d "frontend/dist" ]]; then
    return 0
  fi

  # 找到 dist 目录中最新的文件时间戳（作为上次构建的时间基准）
  local dist_latest
  dist_latest="$(find frontend/dist -type f -printf '%T@\n' 2>/dev/null | sort -rn | head -1)"

  # macOS 的 find 不支持 -printf，用 stat 兜底
  if [[ -z "$dist_latest" ]]; then
    dist_latest="$(find frontend/dist -type f -exec stat -f '%m' {} + 2>/dev/null | sort -rn | head -1)"
  fi

  if [[ -z "$dist_latest" ]]; then
    return 0
  fi

  # 检查 src/ 和关键配置文件是否有比 dist 更新的文件
  local src_latest
  src_latest="$(find frontend/src frontend/index.html frontend/package.json frontend/tsconfig.json frontend/vite.config.ts -type f -exec stat -f '%m' {} + 2>/dev/null | sort -rn | head -1)"

  if [[ -z "$src_latest" ]]; then
    # 如果拿不到源码时间戳，保守地跳过构建
    return 1
  fi

  # 比较：源码最新时间 > dist 最新时间 → 需要重建（整数秒比较）
  if [[ "$src_latest" -gt "$dist_latest" ]]; then
    return 0
  fi

  return 1
}

auto_build_frontend() {
  if ! frontend_needs_build; then
    echo "[INFO] 前端已是最新，跳过构建。"
    return 0
  fi

  echo "[INFO] 检测到前端源码有更新，自动重新构建..."

  # 检查 node 和 npm 是否可用
  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo "[WARN] 未找到 node/npm，无法自动构建前端。"
    echo "[WARN] 请手动执行: cd frontend && npm run build"
    if [[ ! -d "frontend/dist" ]]; then
      echo "[ERROR] 且 frontend/dist 不存在，无法启动。"
      exit 1
    fi
    return 0
  fi

  # 检查 node_modules 是否存在
  if [[ ! -d "frontend/node_modules" ]]; then
    echo "[INFO] 未找到 frontend/node_modules，先安装依赖..."
    (cd frontend && npm install --no-audit --fund=false)
  fi

  # 执行构建
  if (cd frontend && npm run build); then
    echo "[INFO] ✅ 前端构建成功！"
  else
    echo "[WARN] ⚠️ 前端构建失败。"
    if [[ -d "frontend/dist" ]]; then
      echo "[WARN] 将使用上一次的构建产物继续启动。"
    else
      echo "[ERROR] 且 frontend/dist 不存在，无法启动。"
      exit 1
    fi
  fi
}

auto_build_frontend

exec "$PYTHON_CMD" ShengWen-app.py
