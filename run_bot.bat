@echo off
cd /d "%~dp0"
:loop
"..\dota_automaton\.venv\Scripts\python.exe" blimp_bot.py --auto
if %errorlevel%==3 goto loop
pause
