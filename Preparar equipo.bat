@echo off
rem Una sola vez en el equipo que procesa los datos: crea el entorno de Python
rem (.venv) e instala lo que necesita el pipeline. Requiere Python 3.12 instalado
rem (https://www.python.org/downloads/) y Google Chrome (para REPS y SIVICAP).
cd /d "%~dp0"
py -3.12 -m venv .venv || python -m venv .venv || goto :error
.venv\Scripts\python.exe -m pip install --upgrade pip || goto :error
.venv\Scripts\python.exe -m pip install -r requirements-pipeline.txt || goto :error
echo.
echo Listo. Siguientes pasos:
echo   1. "Renovar sesion SIVICAP.bat"  (inicio de sesion en SIVICAP para el IRCA)
echo   2. "Actualizar datos.bat"        (descarga y procesa todas las fuentes)
pause
exit /b 0
:error
echo.
echo No se pudo preparar el equipo. Revise el mensaje de error de arriba.
pause
exit /b 1
