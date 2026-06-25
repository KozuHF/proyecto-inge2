@echo off
cd /d C:\Users\ivann\Desktop\Proyecto_Club360
call .venv\Scripts\activate.bat
python manage.py procesar_invitaciones_vencidas
python manage.py verificar_plazos_abonos_mensuales
python manage.py procesar_senados_ausentes
