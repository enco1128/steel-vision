@echo off
rem SteelVision backend launcher for scheduled task / Startup folder.
cd /d "%~dp0.."
py -3.12 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
