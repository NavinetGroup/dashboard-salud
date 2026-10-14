@echo off
rem Ciclo mensual en el equipo que procesa los datos:
rem   1. descarga y procesa todas las fuentes, controla la calidad y genera
rem      la base del visor (data\dist\)
rem   2. si todo salio bien, ofrece publicarla para que los tableros se
rem      actualicen solos (requiere "gh auth login" una vez)
cd /d "%~dp0"
.venv\Scripts\python.exe -m pipeline.runner --monthly
if errorlevel 2 (
    echo.
    echo No se genero una base nueva: revise el registro de arriba.
    pause
    exit /b 2
)
echo.
.venv\Scripts\python.exe tools\publicar_datos.py
pause
