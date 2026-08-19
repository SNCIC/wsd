@echo off
title Odoo 19 - mes
echo Starting Odoo (mes) ...
echo Browser: http://localhost:8069   (admin / admin)
cd /d D:\odoo19e20250921-f
D:\ProgramDatas\Anaconda\envs\odoo19\python.exe D:\odoo19e20250921-f\odoo-bin -c D:\wsd\odoo.local.conf -d mes
pause
