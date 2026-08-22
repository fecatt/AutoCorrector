@echo off
chcp 65001 >nul 2>&1

:: Проверяем наличие Python
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo Python не найден!
    echo.
    echo Скачайте и установите Python с официального сайта:
    echo   https://www.python.org/downloads/
    echo.
    echo При установке ОБЯЗАТЕЛЬНО поставьте галочку "Add Python to PATH".
    echo.
    goto :end
)

:: Проверяем и устанавливаем зависимости автоматически
python -c "import requests, yaml, pyperclip" >nul 2>&1
if errorlevel 1 (
    echo Установка недостающих библиотек...
    python -m pip install requests pyyaml pyperclip win11toast >nul 2>&1
    if errorlevel 1 (
        echo Ошибка установки зависимостей!
        echo Установите вручную: pip install requests pyyaml pyperclip win11toast
        goto :end
    )
    echo Зависимости установлены!
)

if "%1"=="--install" (
    echo.
    echo Установка автозагрузки...
    python main.py --install
    goto :end
)

if "%1"=="--uninstall" (
    echo.
    echo Удаление из автозагрузки...
    python main.py --uninstall
    goto :end
)

python main.py

:end
echo.
pause
