@echo off
cd /d C:\Users\ivann\Desktop\Proyecto_Club360
call .venv\Scripts\activate.bat

:: Correr tasks al inicio
python manage.py procesar_invitaciones_vencidas
python manage.py verificar_plazos_abonos_mensuales
python manage.py procesar_senados_ausentes

:: Loop de tasks cada hora en segundo plano
start /b cmd /c "cd /d C:\Users\ivann\Desktop\Proyecto_Club360 && call .venv\Scripts\activate.bat && :loop && timeout /t 3600 /nobreak >nul && python manage.py procesar_invitaciones_vencidas && python manage.py verificar_plazos_abonos_mensuales && python manage.py procesar_senados_ausentes && goto loop"

:: Levantar ngrok en segundo plano
start /b %TEMP%\ngrok_extracted\ngrok.exe http 8000

:: Levantar el server
python manage.py runserver 8000
