@echo off
chcp 65001 >nul 2>&1
title OPF 隐私信息检测平台

echo.
echo ========================================
echo   OPF 隐私信息检测平台
echo ========================================
echo.

:: ─── 检查 Docker ─────────────────────────────────────
docker version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Docker Desktop
    echo   安装：https://docs.docker.com/desktop/install/windows-install/
    echo   安装后启动 Docker Desktop，等鲸鱼图标变绿后重试。
    pause
    exit /b 1
)
echo [√] Docker 已就绪

docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] Docker 未启动，请先启动 Docker Desktop
    pause
    exit /b 1
)
echo [√] Docker 服务运行中

:: ─── 检测是否已有旧版本 ─────────────────────────────
set IS_UPGRADE=0
docker images --format "{{.Repository}}" 2>nul | findstr "opf-web" >nul 2>&1
if %errorlevel% equ 0 set IS_UPGRADE=1
docker ps -a --format "{{.Names}}" 2>nul | findstr "opf-web" >nul 2>&1
if %errorlevel% equ 0 set IS_UPGRADE=1

echo.
if %IS_UPGRADE% equ 1 (
    echo [..] 检测到旧版本，进入升级模式
) else (
    echo [..] 首次安装
)

:: ─── 升级：自动备份白名单和敏感词库 ─────────────────
set BACKUP_DIR=
if %IS_UPGRADE% equ 1 (
    if exist "whitelist\pii_whitelist.json" (
        set BACKUP_DIR=whitelist_backup_%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%
        set BACKUP_DIR=!BACKUP_DIR: =0!
        echo.
        echo [..] 自动备份白名单和敏感词库...
        mkdir "!BACKUP_DIR!" 2>nul
        if exist "whitelist\pii_whitelist.json" (
            copy "whitelist\pii_whitelist.json" "!BACKUP_DIR!\" >nul 2>&1
            echo    [√] pii_whitelist.json
        )
        if exist "whitelist\pii_dictionary.json" (
            copy "whitelist\pii_dictionary.json" "!BACKUP_DIR!\" >nul 2>&1
            echo    [√] pii_dictionary.json
        )
        echo    备份位置: !BACKUP_DIR!
    )
)

:: ─── 升级：停止旧容器 ─────────────────────────────────
if %IS_UPGRADE% equ 1 (
    echo.
    echo [..] 停止旧容器...
    docker compose down 2>nul
    echo [√] 已停止
)

:: ─── OPF 模型 ─────────────────────────────────────────
set MODEL_DIR=%USERPROFILE%\.opf\privacy_filter
if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%"

echo.
if exist "%MODEL_DIR%\model.safetensors" (
    echo [√] OPF 模型已存在
) else if exist "model\model.safetensors" (
    echo [..] 复制 OPF 模型...
    copy "model\*" "%MODEL_DIR%\" >nul 2>&1
    echo [√] 已复制
) else (
    echo [..] 首次运行，下载 OPF 模型（~2.8GB，请耐心等待）...
    pip install -q huggingface_hub 2>nul || pip3 install -q huggingface_hub 2>nul
    if %errorlevel% neq 0 (
        echo [错误] pip 未找到，请先安装 Python 3.8+
        echo   https://www.python.org/downloads/
        pause
        exit /b 1
    )
    python -c "from huggingface_hub import snapshot_download; snapshot_download('openai/privacy_filter', local_dir=r'%MODEL_DIR%', local_dir_use_symlinks=False)"
    if %errorlevel% neq 0 (
        echo.
        echo [错误] 模型下载失败
        echo   可能原因：网络无法访问 HuggingFace
        echo   解决：手动下载 model 文件到 %MODEL_DIR%\
        echo   参考：https://huggingface.co/openai/privacy_filter
        pause
        exit /b 1
    )
    echo [√] 模型下载完成
)

:: ─── 构建启动 ─────────────────────────────────────────
echo.
if %IS_UPGRADE% equ 1 (
    echo [..] 重建容器并启动...
) else (
    echo [..] 构建容器（首次约 5-10 分钟）...
)
echo.
docker compose up --build -d
if %errorlevel% neq 0 (
    echo.
    echo [错误] 构建失败
    echo   常见原因：Docker Desktop 内存不足（需 12GB+）
    pause
    exit /b 1
)

:: ─── 恢复备份 ─────────────────────────────────────────
if defined BACKUP_DIR (
    if exist "!BACKUP_DIR!" (
        echo.
        echo [..] 恢复白名单和敏感词库...
        if exist "!BACKUP_DIR!\pii_whitelist.json" (
            copy "!BACKUP_DIR!\pii_whitelist.json" "whitelist\" >nul 2>&1
            echo    [√] pii_whitelist.json
        )
        if exist "!BACKUP_DIR!\pii_dictionary.json" (
            copy "!BACKUP_DIR!\pii_dictionary.json" "whitelist\" >nul 2>&1
            echo    [√] pii_dictionary.json
        )
    )
)

echo.
echo [..] 等待服务启动...
timeout /t 15 /nobreak >nul

:: ─── 完成 ──────────────────────────────────────────────
set WEB_PORT=8081

echo.
echo ========================================
if %IS_UPGRADE% equ 1 (
    echo   [√] 升级完成！
) else (
    echo   [√] 安装完成！
)
echo.
echo   浏览器访问：http://localhost:%WEB_PORT%
echo.
echo   管理命令：
echo     启动：docker compose up -d
echo     停止：docker compose down
echo     重启：docker compose restart
echo     日志：docker compose logs -f
echo ========================================
echo.

start http://localhost:%WEB_PORT%
pause
