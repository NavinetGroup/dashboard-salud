@echo off
rem Abre Chrome en SIVICAP para iniciar sesion a mano (el reCAPTCHA lo resuelve
rem una persona). La sesion queda guardada y el scraper de IRCA la reutiliza
rem durante varias semanas. Repetir cuando el pipeline avise que SIVICAP pide login.
cd /d "%~dp0"
.venv\Scripts\python.exe tools\setup_sivicap_session.py
pause
