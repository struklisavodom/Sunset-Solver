@echo off
rem Starts the helper without a console window. The status bar appears bottom-left.
rem Double-click the bar to open the web pages, right-click it to quit.
cd /d "%~dp0"
where pythonw >nul 2>nul && (start "" pythonw app.py --no-browser) || (start "" pyw app.py --no-browser)
