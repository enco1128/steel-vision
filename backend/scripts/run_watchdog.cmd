@echo off
rem SteelVision watchdog launcher for scheduled task / Startup folder.
rem Probes /api/health every 10s; on 3 consecutive failures restarts the backend.
cd /d "%~dp0.."
py -3.12 scripts\watchdog.py --port 8000
