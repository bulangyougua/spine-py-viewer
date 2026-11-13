@echo off
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onefile --windowed --name SpineViewer --add-data "web;web" --add-data "vendor;vendor" main.py
if errorlevel 1 (
  echo Build failed.
  exit /b 1
)
copy /y dist\SpineViewer.exe SpineViewer.exe >nul
echo OK: %cd%\SpineViewer.exe
