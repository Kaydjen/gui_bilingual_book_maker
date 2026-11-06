@echo off
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 start.pyw %* & exit /b)
where pythonw >nul 2>nul && (start "" pythonw start.pyw %* & exit /b)
echo Python 3.11 or newer is required: https://www.python.org/downloads/
pause
