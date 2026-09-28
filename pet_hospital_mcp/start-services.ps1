# 宠物医院 MCP 服务自启脚本
# 由计划任务"PetHospitalMCP"在用户登录时调用。
# 行为：分别检查 8080（Go 后端）与 8000（MCP 服务），未监听才启动，避免重复拉起。

$ErrorActionPreference = "SilentlyContinue"

$backendExe   = "E:\pet\windows\pethospital.exe"
$backendCwd   = "E:\pet\windows"
$mcpDir       = "E:\pet\windows\pet_hospital_mcp"
$mcpPython    = "E:\pet\windows\pet_hospital_mcp\.venv\Scripts\python.exe"

# 1) Go 宠物医院后端 -> 127.0.0.1:8080
$p8080 = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if (-not $p8080) {
    Start-Process -FilePath $backendExe -WorkingDirectory $backendCwd -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

# 2) MCP 服务 -> 127.0.0.1:8000
$p8000 = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if (-not $p8000) {
    Start-Process -FilePath $mcpPython -ArgumentList "-m", "pet_hospital_mcp" -WorkingDirectory $mcpDir -WindowStyle Hidden
}
