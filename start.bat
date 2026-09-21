@echo off
cd /d "%~dp0"
start "" /b cmd /c "for /l %%i in (1,1,120) do (curl -s -o nul http://127.0.0.1:5173 && (start "" http://127.0.0.1:5173 & exit) || timeout /t 2 /nobreak >nul)"
docker compose up --build
