@echo off
chcp 65001 >nul
title 宠物医院 MCP 一键启动
cd /d E:\pet\windows\pet_hospital_mcp

echo ============================================
echo  宠物医院 MCP 服务启动器
echo ============================================
echo.

echo [1/2] 启动 Go 宠物医院后端 (127.0.0.1:8080) ...
start "PetHospital-Backend" "E:\pet\windows\pethospital.exe"
timeout /t 2 /nobreak >nul

echo [2/2] 启动 MCP 服务 (127.0.0.1:8000) ...
echo       保持本窗口开启；按 Ctrl+C 可停止服务
echo.
.venv\Scripts\python.exe -m pet_hospital_mcp

pause
