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

if [[ ! -d "frontend/dist" ]]; then
  echo "[ERROR] 未找到前端构建目录 frontend/dist。"
  echo "[ERROR] 请先执行 ./deploy一键部署.sh 或手动运行 frontend/npm run build。"
  exit 1
fi

exec "$PYTHON_CMD" ShengWen-app.py
