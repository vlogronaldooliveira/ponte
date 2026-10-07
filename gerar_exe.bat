@echo off
echo Instalando dependencias...
python -m pip install --upgrade pyinstaller pynput tkinterdnd2 requests websocket-client pywin32
echo.
echo Gerando Ponte.exe...
python -m PyInstaller --noconsole --onefile --name Ponte --collect-all tkinterdnd2 ponte.py
echo.
echo Pronto! O programa esta em: dist\Ponte.exe
pause
