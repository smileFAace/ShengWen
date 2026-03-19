#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

NODE_MIN_MAJOR=20
PYTHON_MIN_MAJOR=3
PYTHON_MIN_MINOR=10
VENV_DIR=".venv"

info() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
err() { echo "[ERROR] $*" >&2; }

require_cmd() {
  local cmd="$1"
  local hint="${2:-}"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    err "缺少命令: $cmd"
    if [[ -n "$hint" ]]; then
      err "$hint"
    fi
    exit 1
  fi
}

detect_linux_pkg_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "apt"
    return
  fi
  if command -v dnf >/dev/null 2>&1; then
    echo "dnf"
    return
  fi
  if command -v yum >/dev/null 2>&1; then
    echo "yum"
    return
  fi
  if command -v pacman >/dev/null 2>&1; then
    echo "pacman"
    return
  fi
  if command -v zypper >/dev/null 2>&1; then
    echo "zypper"
    return
  fi
  echo ""
}

install_linux_deps() {
  local mgr
  mgr="$(detect_linux_pkg_manager)"
  if [[ -z "$mgr" ]]; then
    warn "未识别包管理器，跳过自动安装系统依赖。请手动安装: git python3-venv"
    return
  fi

  local no_sudo_action="skip"
  if ! command -v sudo >/dev/null 2>&1 || ! sudo -n true >/dev/null 2>&1; then
    warn "当前没有 sudo 权限，无法自动安装系统依赖。"
    if [[ -t 0 ]]; then
      echo "请选择后续操作："
      echo "1) 跳过系统依赖安装并继续（推荐）"
      echo "2) 退出脚本，稍后以有 sudo 权限的用户运行"
      echo "3) 打印手动安装命令后继续"
      read -r -p "请输入 1/2/3（默认 1）: " choice
      case "${choice:-1}" in
        2) no_sudo_action="exit" ;;
        3) no_sudo_action="print" ;;
        *) no_sudo_action="skip" ;;
      esac
    fi
  fi

  if [[ "$no_sudo_action" == "exit" ]]; then
    err "已退出。请在具备 sudo 权限的环境中重试。"
    exit 1
  fi

  if [[ "$no_sudo_action" == "print" ]]; then
    echo "可手动执行的安装命令（按你的系统选择）："
    case "$mgr" in
      apt) echo "sudo apt-get update && sudo apt-get install -y git python3-venv" ;;
      dnf) echo "sudo dnf install -y git python3 python3-pip python3-virtualenv" ;;
      yum) echo "sudo yum install -y git python3 python3-pip" ;;
      pacman) echo "sudo pacman -Sy --noconfirm git python python-virtualenv" ;;
      zypper) echo "sudo zypper --non-interactive install git python3 python3-pip python3-virtualenv" ;;
    esac
  fi

  if ! command -v sudo >/dev/null 2>&1 || ! sudo -n true >/dev/null 2>&1; then
    warn "跳过自动安装系统依赖。请确保已安装: git python3-venv"
    return
  fi

  info "检测到缺失系统依赖，尝试自动安装（需要 sudo）..."
  case "$mgr" in
    apt)
      sudo apt-get update
      sudo apt-get install -y git python3-venv
      ;;
    dnf)
      sudo dnf install -y git python3 python3-pip python3-virtualenv
      ;;
    yum)
      sudo yum install -y git python3 python3-pip
      ;;
    pacman)
      sudo pacman -Sy --noconfirm git python python-virtualenv
      ;;
    zypper)
      sudo zypper --non-interactive install git python3 python3-pip python3-virtualenv
      ;;
  esac
}

print_node_upgrade_macos() {
  echo "macOS 更新 Node.js 的常见方式："
  echo "1) 使用 Homebrew: brew install node@20 或 brew upgrade node"
  echo "2) 使用 nvm: nvm install 20 && nvm use 20"
}

warn_macos_missing_deps() {
  local missing=0
  if ! "$PYTHON_CMD" -m venv --help >/dev/null 2>&1; then
    warn "当前 Python 缺少 venv 模块，无法创建虚拟环境。"
    if command -v brew >/dev/null 2>&1; then
      echo "可执行: brew install python@3.10"
    else
      echo "请安装/升级 Python 3.10+（推荐使用 Homebrew 或 pyenv）"
    fi
    missing=1
  fi
  return "$missing"
}

select_python_cmd() {
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

check_python_version() {
  local py_cmd="$1"
  "$py_cmd" - <<'PY'
import sys
major, minor = sys.version_info[:2]
need_major, need_minor = 3, 10
if (major, minor) < (need_major, need_minor):
    raise SystemExit(f"Python 版本过低: {major}.{minor}，需要 >= {need_major}.{need_minor}")
print(f"Python 版本: {major}.{minor} (ok)")
if (major, minor) >= (3, 14):
    print("[WARN] 当前 Python 版本高于 3.13，虽然部署过程会继续，但部分依赖可能安装很久甚至卡住")
    print("[WARN] 如遇到依赖安装异常缓慢，建议改用 Python 3.12 或 3.13")
PY
}

check_node_version() {
  local node_major
  node_major="$(node -p "process.versions.node.split('.')[0]")"
  if [[ "$node_major" -lt "$NODE_MIN_MAJOR" ]]; then
    err "Node.js 版本过低: $(node -v)，需要 >= ${NODE_MIN_MAJOR}.x（当前前端依赖 Vite 7）"
    if [[ "$(uname -s)" == "Linux" ]]; then
      if maybe_upgrade_node_linux; then
        node_major="$(node -p "process.versions.node.split('.')[0]")"
      fi
    elif [[ "$(uname -s)" == "Darwin" ]]; then
      print_node_upgrade_macos
    fi
    if [[ "$node_major" -lt "$NODE_MIN_MAJOR" ]]; then
      exit 1
    fi
  fi
  info "Node.js 版本: $(node -v) (ok)"
}

print_nodesource_instructions() {
  echo "可手动更新 Node.js（适用于 Ubuntu/Debian）："
  echo "1) sudo apt remove --purge nodejs npm"
  echo "2) sudo apt autoremove"
  echo "3) curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -"
  echo "4) sudo apt install -y nodejs"
  echo "如需国内镜像，可将 deb.nodesource.com 替换为 mirrors.aliyun.com/nodesource"
}

maybe_upgrade_node_linux() {
  local mgr
  mgr="$(detect_linux_pkg_manager)"
  if [[ "$mgr" != "apt" ]]; then
    warn "仅支持在 Ubuntu/Debian(apt) 上自动更新 Node.js，请手动更新后重试。"
    return 1
  fi

  if ! command -v sudo >/dev/null 2>&1 || ! sudo -n true >/dev/null 2>&1; then
    warn "当前没有 sudo 权限，无法自动更新 Node.js。"
    print_nodesource_instructions
    return 1
  fi

  if ! command -v curl >/dev/null 2>&1; then
    warn "缺少 curl，无法自动更新 Node.js。请先安装 curl 或手动更新。"
    print_nodesource_instructions
    return 1
  fi

  local do_install="no"
  if [[ -t 0 ]]; then
    read -r -p "检测到 Node.js 版本过低，是否自动更新到 20.x？[Y/n]: " choice
    case "${choice:-Y}" in
      n|N) do_install="no" ;;
      *) do_install="yes" ;;
    esac
  fi

  if [[ "$do_install" != "yes" ]]; then
    warn "已跳过自动更新 Node.js。"
    print_nodesource_instructions
    return 1
  fi

  info "准备通过 NodeSource 安装 Node.js 20.x（需要 sudo）..."
  sudo apt remove --purge -y nodejs npm || true
  sudo apt autoremove -y || true
  sudo bash -c "curl -fsSL https://deb.nodesource.com/setup_20.x | bash -"
  sudo apt install -y nodejs
  return 0
}

ensure_frontend_permissions() {
  local targets=("." "package.json")
  if [[ -e "package-lock.json" ]]; then
    targets+=("package-lock.json")
  fi
  if [[ -d "node_modules" ]]; then
    targets+=("node_modules")
  fi

  local needs_fix=0
  local target
  for target in "${targets[@]}"; do
    if [[ ! -w "$target" ]]; then
      needs_fix=1
      break
    fi
  done

  if [[ "$needs_fix" -eq 0 ]]; then
    info "前端目录权限正常"
    return 0
  fi

  warn "检测到前端目录写权限异常，尝试自动修复"

  if [[ "$(id -u)" -eq 0 ]]; then
    chown -R "${SUDO_UID:-0}:${SUDO_GID:-0}" node_modules package-lock.json 2>/dev/null || true
  elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    local fix_targets=()
    for target in "${targets[@]}"; do
      if [[ -e "$target" && ! -w "$target" ]]; then
        fix_targets+=("$target")
      fi
    done
    if [[ "${#fix_targets[@]}" -gt 0 ]]; then
      sudo chown -R "$(id -u):$(id -g)" "${fix_targets[@]}"
    fi
  else
    err "前端目录不可写且无法使用 sudo 自动修复，请执行: sudo chown -R $(id -u):$(id -g) frontend/node_modules frontend/package-lock.json"
    return 1
  fi

  for target in "${targets[@]}"; do
    if [[ -e "$target" && ! -w "$target" ]]; then
      err "权限修复失败: $target 仍不可写"
      return 1
    fi
  done

  info "前端目录权限修复完成"
  return 0
}

has_proxy_env() {
  local proxy_vars=(http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy NO_PROXY no_proxy)
  local var
  for var in "${proxy_vars[@]}"; do
    if [[ -n "${!var:-}" ]]; then
      return 0
    fi
  done
  return 1
}

install_frontend_deps() {
  local npm_cmd=(npm install --no-audit --fund=false)
  if [[ -f package-lock.json ]]; then
    npm_cmd=(npm ci --no-audit --fund=false)
  fi

  info "开始安装前端依赖"
  if "${npm_cmd[@]}"; then
    info "前端依赖安装成功"
    return 0
  fi

  if has_proxy_env; then
    warn "检测到代理环境，尝试无代理重试"
    if env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy -u NO_PROXY -u no_proxy "${npm_cmd[@]}"; then
      info "无代理重试成功"
      return 0
    fi
  fi

  err "前端依赖安装失败"
  return 1
}

echo "=========================================="
echo "  ShengWen 一键部署脚本 (Linux/macOS)"
echo "=========================================="
echo

if [[ "$(id -u)" -eq 0 ]]; then
  err "请不要使用 sudo 或 root 运行本脚本。"
  err "正确做法：使用普通用户运行 ./deploy一键部署.sh，脚本会在需要系统权限时单独调用 sudo。"
  err "如果你之前用 sudo 执行过 npm，可先修复权限：sudo chown -R $(id -u):$(id -g) frontend/node_modules frontend/package-lock.json ~/.npm"
  exit 1
fi

require_cmd git "请先安装 Git。"
require_cmd node "请先安装 Node.js ${NODE_MIN_MAJOR}+。"
require_cmd npm "请先安装 npm（通常随 Node.js 提供）。"

PYTHON_CMD="$(select_python_cmd)"
if [[ -z "$PYTHON_CMD" ]]; then
  err "未找到 Python，请先安装 Python ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}+"
  exit 1
fi

if [[ "$(uname -s)" == "Linux" ]]; then
  need_install=0
  "$PYTHON_CMD" -m venv --help >/dev/null 2>&1 || need_install=1
  if [[ "$need_install" -eq 1 ]]; then
    install_linux_deps
  fi
elif [[ "$(uname -s)" == "Darwin" ]]; then
  warn_macos_missing_deps || true
fi

check_python_version "$PYTHON_CMD"
check_node_version

if ! "$PYTHON_CMD" -m venv --help >/dev/null 2>&1; then
  err "当前 Python 缺少 venv 模块。Linux 请安装 python3-venv；macOS 建议安装/升级 Python 3.10+。"
  exit 1
fi

info "步骤 1/5: 创建或复用虚拟环境 ${VENV_DIR}"
if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_CMD" -m venv "$VENV_DIR"
fi

if [[ -f "${VENV_DIR}/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${VENV_DIR}/bin/activate"
else
  err "未找到虚拟环境激活脚本: ${VENV_DIR}/bin/activate"
  exit 1
fi

info "步骤 2/5: 安装后端依赖"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt

info "步骤 3/5: 安装前端依赖"
pushd frontend >/dev/null
ensure_frontend_permissions
install_frontend_deps

info "步骤 4/5: 构建前端"
npm run build
popd >/dev/null

info "步骤 5/5: 准备配置文件"
mkdir -p config
if [[ ! -f config/settings.json && -f config/settings.example.json ]]; then
  cp config/settings.example.json config/settings.json
  info "已创建 config/settings.json"
else
  info "保留现有配置文件（若不存在，首次启动会自动生成默认配置）"
fi

echo
echo "=========================================="
echo "✅ 部署完成！"
echo "=========================================="
echo
echo "下一步操作："
echo "1. 启动服务: chmod +x ./run一键启动.sh && ./run一键启动.sh  或者  source ${VENV_DIR}/bin/activate && python ShengWen-app.py"
echo "2. 打开浏览器访问: http://localhost:8000/"
echo "3. 在前端设置面板中填写 LLM 与转录参数"
echo
