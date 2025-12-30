@echo off
echo ========================================
echo Edge-TTS Backend Indito
echo ========================================

REM Python virtual environment aktiválása (ha van)
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

REM Függőségek telepítése (ha szükséges)
echo Függőségek ellenőrzése...
pip install -r requirements.txt

REM Backend indítása
echo Backend indítása: http://localhost:8000
python main.py

pause
