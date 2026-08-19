@echo off
REM ===============================================================
REM  P&G ar-figyelo - Windows inditó
REM  Elso futaskor letrehozza a virtualis kornyezetet es telepit
REM  minden fuggoseget (kb. 2-3 perc). Utana mar azonnal indul.
REM ===============================================================
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [HIBA] Nem talalhato a Python. Telepitsd innen: https://www.python.org/downloads/
  echo        A telepitesnel pipald ki az "Add python.exe to PATH" opciot!
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Virtualis kornyezet letrehozasa...
  python -m venv .venv
)

call ".venv\Scripts\activate.bat"

if not exist ".venv\.deps_ok" (
  echo Fuggosegek telepitese... ^(elso inditas, eltarthat par percig^)
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [HIBA] A telepites nem sikerult.
    pause
    exit /b 1
  )
  echo Chromium bongeszo telepitese a dm.hu-hoz...
  python -m playwright install chromium
  echo ok> ".venv\.deps_ok"
)

echo.
echo Inditas... a bongeszo automatikusan megnyilik: http://127.0.0.1:5000
echo Leallitas: ezen az ablakon Ctrl+C
echo.
python app.py
pause
