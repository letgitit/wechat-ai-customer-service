param(
    [string]$Config = "config.local.toml",
    [string]$Python = ".venv\Scripts\python.exe"
)
$ErrorActionPreference = "Stop"
# 默认且仅只读；发送授权必须使用 README 中单独的有限运行命令。
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Write-Output "BLOCKED: Windows native desktop required"
    exit 2
}
if (!(Test-Path $Python) -or !(Test-Path $Config)) {
    Write-Output "BLOCKED: Python environment or local config missing"
    exit 2
}
& $Python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,11) else 2)"
if ($LASTEXITCODE -ne 0) {
    Write-Output "BLOCKED: Python 3.11 required"
    exit 2
}
& $Python -m wechat_cs doctor --adapter wxauto --config $Config --report reports/doctor-windows.json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m wechat_cs run --adapter wxauto --config $Config --dry-run --reply-engine fixed --duration-seconds 60
exit $LASTEXITCODE
