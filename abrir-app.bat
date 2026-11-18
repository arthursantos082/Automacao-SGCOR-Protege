@echo off
rem Abre o app de renovações (versão de desenvolvimento; o .exe vem na F4)
cd /d "%~dp0"
set PYTHONPATH=src
start "" ".venv\Scripts\pythonw.exe" -m sgcor_renov.ui
