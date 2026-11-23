@echo off
rem SteelVision 一键回归：报警规则/判级/复核状态机/鉴权矩阵/API 冒烟
cd /d %~dp0..
py -3.12 -m pytest tests %*
