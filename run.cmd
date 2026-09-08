@echo off
rem Start the FIT viewer/editor for the .fit files in this folder.
setlocal
cd /d "%~dp0"
py -3 -m fitedit --dir "%~dp0" %*
