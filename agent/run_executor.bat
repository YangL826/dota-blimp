@echo off
cd /d "%~dp0"
"..\..\dota_automaton\.venv\Scripts\python.exe" executor.py %*
