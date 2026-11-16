@echo off
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 novel.pyw %* & exit /b)
where pythonw >nul 2>nul && (start "" pythonw novel.pyw %* & exit /b)
echo Python 3.11 or newer is required: https://www.python.org/downloads/
pause
