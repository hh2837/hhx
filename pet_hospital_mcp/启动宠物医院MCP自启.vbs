' 宠物医院 MCP 服务自启（隐藏窗口方式）
' 由 Windows 启动文件夹在用户登录时调用
Set ws = CreateObject("Wscript.Shell")
ws.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""E:\pet\windows\pet_hospital_mcp\start-services.ps1""", 0, False
