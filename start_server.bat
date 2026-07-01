@echo off
cd /d C:\Users\ivann\Desktop\Proyecto_Club360
call .venv\Scripts\activate.bat

:: Correr tasks al inicio
python manage.py procesar_invitaciones_vencidas
python manage.py verificar_plazos_abonos_mensuales
python manage.py procesar_senados_ausentes

:: Las tasks periodicas ahora las corre la tarea programada de Windows
:: "Club360_ProcesarVencimientos" (cada hora, en punto), independiente de
:: que este server este prendido. Ver tasks/procesar_vencimientos.bat

:: Levantar ngrok en segundo plano
start /b %TEMP%\ngrok_extracted\ngrok.exe http 8000

:: Levantar el server
python manage.py runserver 8000
