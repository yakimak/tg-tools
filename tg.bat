@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto run

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
) else (
    set "PY=python"
)

%PY% -m venv .venv
if errorlevel 1 (
    echo Не удалось создать виртуальное окружение. Установите Python 3.10+.
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo Не удалось установить зависимости.
    exit /b 1
)

:run
".venv\Scripts\python.exe" tg.py %*
set "CODE=%errorlevel%"
if "%~1"=="" pause
exit /b %CODE%
