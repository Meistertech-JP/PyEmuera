@echo off
rem PyEmuera launcher.
rem  - Drag a game folder (the folder that contains ERB and CSV) onto this file, or
rem  - put this file and PyEmuera.pyz inside the game folder and double-click it.
rem The exit code of PyEmuera is returned unchanged.
setlocal
set "PYZ=%~dp0PyEmuera.pyz"
if not exist "%PYZ%" goto nopyz
call :findpython
if not defined PYEXE goto nopython
%PYEXE% "%PYZ%" %*
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="0" exit /b 0
echo.
echo PyEmuera stopped (exit code %RESULT%). Read the message above.
echo See HOW_TO_USE_ja.txt, section 9 "Troubleshooting".
call :wait
exit /b %RESULT%

:nopyz
echo PyEmuera.pyz was not found next to this file.
echo Extract the whole ZIP first, and keep PyEmuera.pyz in the same folder as this file.
call :wait
exit /b 1

:nopython
echo Python 3.10 or later was not found.
echo Install Python, then run this file again. See HOW_TO_USE_ja.txt, section 2.
call :wait
exit /b 9009

:wait
rem Set PYEMUERA_NO_PAUSE=1 to skip the key prompt (for scripts and automated tests).
if not defined PYEMUERA_NO_PAUSE pause
exit /b 0

:findpython
rem Probe only; never start an automatic Python download or wait for input here.
set "PYEXE="
set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"
where py >nul 2>nul
if errorlevel 1 goto trypython
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" <nul >nul 2>nul
if errorlevel 1 goto trypython
set "PYEXE=py -3"
exit /b 0
:trypython
where python >nul 2>nul
if errorlevel 1 exit /b 0
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" <nul >nul 2>nul
if errorlevel 1 exit /b 0
set "PYEXE=python"
exit /b 0
