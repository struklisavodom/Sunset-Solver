@echo off
rem Run once. Puts "Sunset Canyon Helper" on your Desktop; right-click it and choose "Pin to taskbar".
cd /d "%~dp0"
for /f "usebackq delims=" %%i in (`python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"`) do set "PYW=%%i"
if not exist "%PYW%" (echo Could not find pythonw.exe next to python. & pause & exit /b 1)
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Sunset Canyon Helper.lnk'); $s.TargetPath='%PYW%'; $s.Arguments='app.py --no-browser'; $s.WorkingDirectory='%CD%'; $s.IconLocation='%CD%\icon.ico'; $s.Save()"
echo.
echo Shortcut created on your Desktop: "Sunset Canyon Helper".
echo Right-click it and choose "Pin to taskbar" (on Windows 11: Show more options first).
pause
