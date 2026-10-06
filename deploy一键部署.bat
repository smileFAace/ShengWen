@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "NODE_MIN_MAJOR=20"
set "VENV_DIR=.venv"
set "PYTHON_EXE="
set "PYTHON_ARGS="

echo ==========================================
echo   ShengWen 一键部署脚本 (Windows)
echo ==========================================
echo.

REM 检查 Node.js
where node >nul 2>nul
if errorlevel 1 (
    echo ❌ 错误: 未找到 Node.js，请先安装 Node.js
    echo 建议安装 Node.js 20+ ^(LTS^) 后重试
    echo 可通过官方安装包或系统包管理器 ^(winget/choco^) 安装
    pause
    exit /b 1
)

for /f %%i in ('node -p "process.versions.node.split('.')[0]"') do set "NODE_MAJOR=%%i"
if not defined NODE_MAJOR (
    echo ❌ 错误: 无法识别 Node.js 版本
    pause
    exit /b 1
)
if !NODE_MAJOR! LSS %NODE_MIN_MAJOR% (
    echo ❌ 错误: Node.js 版本过低 ^(当前: !NODE_MAJOR!，需要: %NODE_MIN_MAJOR%+^)
    echo 请升级 Node.js 后重试，当前前端构建依赖 Vite 7。
    echo 可使用官方安装包或系统包管理器 ^(winget/choco^) 升级到 20+。
    pause
    exit /b 1
)

REM 检查 npm
where npm >nul 2>nul
if errorlevel 1 (
    echo ❌ 错误: 未找到 npm，请先安装 npm
    pause
    exit /b 1
)

REM 检查 Python
where py >nul 2>nul
if not errorlevel 1 (
    py -3.13 -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3.13"
        goto :python_ok
    )
    py -3.12 -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3.12"
        goto :python_ok
    )
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3"
        goto :python_ok
    )
    echo ❌ 错误: 检测到 py 启动器，但无法启动可用的 Python 3.x
    echo 请检查 Python 安装是否完整，建议安装 Python 3.12 或 3.13
    echo 参考命令：py --list
    pause
    exit /b 1
)
where python >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%i in ('where python') do (
        "%%i" -c "import sys" >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON_EXE=%%i"
            goto :python_ok
        )
    )
)
where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
    goto :python_ok
)
echo ❌ 错误: 未找到 Python，请先安装 Python 3.12 或 3.13
echo 建议从官方安装包或系统包管理器 ^(winget/choco^) 安装
echo 安装后重新双击本脚本即可自动继续
pause
exit /b 1

:python_ok
set "PYTHON_VERSION="
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import sys; print(str(sys.version_info[0]) + '.' + str(sys.version_info[1]))" > "%TEMP%\shengwen_python_version.txt" 2>nul
if errorlevel 1 (
    echo ❌ 错误: 无法识别 Python 版本
    echo 请确认已安装 Python 3.x，并可通过 py 启动器或 python 命令访问
    echo 可手动执行以下命令排查：
    echo   py -3 -c "import sys; print(sys.version)"
    echo   python -c "import sys; print(sys.version)"
    if exist "%TEMP%\shengwen_python_version.txt" del /f /q "%TEMP%\shengwen_python_version.txt" >nul 2>nul
    pause
    exit /b 1
)
set /p PYTHON_VERSION=<"%TEMP%\shengwen_python_version.txt"
if exist "%TEMP%\shengwen_python_version.txt" del /f /q "%TEMP%\shengwen_python_version.txt" >nul 2>nul
if not defined PYTHON_VERSION (
    echo ❌ 错误: 无法识别 Python 版本
    echo 请确认已安装 Python 3.x，并可通过 py 启动器或 python 命令访问
    echo 可手动执行以下命令排查：
    echo   py -3 -c "import sys; print(sys.version)"
    echo   python -c "import sys; print(sys.version)"
    pause
    exit /b 1
)
for /f "tokens=1,2 delims=." %%i in ("%PYTHON_VERSION%") do (
    set "PYTHON_VERSION_MAJOR=%%i"
    set "PYTHON_VERSION_MINOR=%%j"
)
echo ℹ️ 当前 Python 版本: %PYTHON_VERSION%
echo ℹ️ 建议 Python 版本: 3.12 或 3.13
if !PYTHON_VERSION_MAJOR! GTR 3 (
    echo ⚠️ 警告: 当前 Python 版本高于 3.13，虽然部署过程会继续，但部分依赖可能安装很久甚至卡住
    echo ⚠️ 如遇到依赖安装异常缓慢，建议改用 Python 3.12 或 3.13
) else if !PYTHON_VERSION_MAJOR!==3 if !PYTHON_VERSION_MINOR! GEQ 14 (
    echo ⚠️ 警告: 当前 Python 版本高于 3.13，虽然部署过程会继续，但部分依赖可能安装很久甚至卡住
    echo ⚠️ 如遇到依赖安装异常缓慢，建议改用 Python 3.12 或 3.13
)

echo ✓ 环境检查通过 ^(Node !NODE_MAJOR!, Python %PYTHON_VERSION%^)
echo.

REM 创建/复用虚拟环境
echo 📦 步骤 1/5: 准备虚拟环境...
set "REBUILD_VENV="
if exist "%VENV_DIR%\pyvenv.cfg" (
    set "TARGET_PYTHON_MAJOR=!PYTHON_VERSION_MAJOR!"
    set "TARGET_PYTHON_MINOR=!PYTHON_VERSION_MINOR!"
    for /f "tokens=2 delims== " %%i in ('findstr /b /c:"version =" "%VENV_DIR%\pyvenv.cfg"') do set "VENV_VERSION_RAW=%%i"
    for /f "tokens=1,2 delims=." %%i in ("!VENV_VERSION_RAW!") do (
        set "VENV_MAJOR=%%i"
        set "VENV_MINOR=%%j"
    )
    if not "!VENV_MAJOR!.!VENV_MINOR!"=="!TARGET_PYTHON_MAJOR!.!TARGET_PYTHON_MINOR!" (
        echo ⚠️ 检测到旧虚拟环境使用的是 Python !VENV_MAJOR!.!VENV_MINOR!，将自动重建为 Python !TARGET_PYTHON_MAJOR!.!TARGET_PYTHON_MINOR!
        set "REBUILD_VENV=1"
    )
)
if defined REBUILD_VENV (
    if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"
)
if not exist "%VENV_DIR%\Scripts\python.exe" (
    "%PYTHON_EXE%" %PYTHON_ARGS% -m venv "%VENV_DIR%" >nul 2>nul
    if errorlevel 1 (
        echo ⚠️ venv 模块不可用，尝试使用 virtualenv...
        "%PYTHON_EXE%" %PYTHON_ARGS% -m pip show virtualenv >nul 2>nul
        if errorlevel 1 (
            echo 📦 正在安装 virtualenv...
            "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install virtualenv
            if errorlevel 1 (
                echo ❌ 安装 virtualenv 失败
                pause
                exit /b 1
            )
        )
        "%PYTHON_EXE%" %PYTHON_ARGS% -m virtualenv "%VENV_DIR%"
        if errorlevel 1 (
            echo ❌ 创建虚拟环境失败
            pause
            exit /b 1
        )
    )
)
set "VENV_PYTHON=%CD%\%VENV_DIR%\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    echo ❌ 错误: 未找到虚拟环境 Python：%VENV_PYTHON%
    pause
    exit /b 1
)

REM 升级 pip 并安装后端依赖
echo 📦 步骤 2/5: 安装后端依赖...
"%VENV_PYTHON%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo ❌ pip 工具升级失败
    pause
    exit /b 1
)
"%VENV_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ❌ 后端依赖安装失败
    pause
    exit /b 1
)

REM 前端构建
echo 📦 步骤 3/5: 安装前端依赖...
cd frontend
set "NPM_INSTALL_CMD=npm install --no-audit --fund=false"
if exist package-lock.json (
    set "NPM_INSTALL_CMD=npm ci --no-audit --fund=false"
)
call %NPM_INSTALL_CMD%
if errorlevel 1 (
    set "HAS_PROXY="
    for %%v in (http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy NO_PROXY no_proxy) do (
        if defined %%v set "HAS_PROXY=1"
    )
    if defined HAS_PROXY (
        echo ⚠️ 检测到代理环境，正在无代理重试...
        call cmd /d /v:on /c "set http_proxy=&set https_proxy=&set HTTP_PROXY=&set HTTPS_PROXY=&set ALL_PROXY=&set all_proxy=&set NO_PROXY=&set no_proxy=& %NPM_INSTALL_CMD%"
    )
)
if errorlevel 1 (
    echo ❌ 前端依赖安装失败
    cd ..
    pause
    exit /b 1
)

echo.
echo 🔨 步骤 4/5: 构建前端...
call npm run build
if errorlevel 1 (
    echo ❌ 前端构建失败
    cd ..
    pause
    exit /b 1
)

cd ..
echo ✓ 前端构建完成
echo.

REM 准备配置文件
echo 📦 步骤 5/5: 准备配置文件...
if not exist config mkdir config
if not exist config\settings.json (
    if exist config\settings.example.json (
        copy /Y config\settings.example.json config\settings.json >nul
        if errorlevel 1 (
            echo ❌ settings.json 创建失败
            pause
            exit /b 1
        )
        echo ✓ 已创建 config\settings.json
    ) else (
        echo ⚠️ 未找到 config\settings.example.json，首次启动将自动生成默认配置
    )
) else (
    echo ✓ 已存在 config\settings.json，保留现有配置
)

echo.
echo ==========================================
echo ✅ 部署完成！
echo ==========================================
echo.
echo 下一步操作：
echo 1. 启动服务: ./run一键启动.bat 或者 .\%VENV_DIR%\Scripts\python.exe ShengWen-app.py
echo 2. 打开浏览器: http://localhost:8000/
echo 3. 在前端设置面板中填写 LLM 与转录参数
echo.
pause
