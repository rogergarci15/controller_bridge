@echo off
rem Doble clic para arrancar el puente Zwift Ride -> MyWhoosh.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo No encuentro el entorno .venv en esta carpeta. Sigue la instalacion del README.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m zwiftplay run %*
echo.
echo El puente se ha detenido.
pause
