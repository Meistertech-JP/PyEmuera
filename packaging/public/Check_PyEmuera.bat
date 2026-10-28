@echo off
rem Static compatibility check. Drag a game folder onto this file.
rem It reads ERB/CSV only and does not start the game. A JSON report is written to the "reports" folder.
rem Exit code: 0 = no known issue, 2 = issues found, other = PyEmuera stopped.
setlocal
set "PYZ=%~dp0PyEmuera.pyz"
if not exist "%PYZ%" goto nopyz
call :findpython
if not defined PYEXE goto nopython
set "OUT=%~dp0reports"
if not exist "%OUT%" mkdir "%OUT%"
set "RUN=%RANDOM%-%RANDOM%"
"%PYEXE%" "%PYZ%" %* --check --report "%OUT%\check-%RUN%.json"
set "RESULT=%ERRORLEVEL%"
echo.
if exist "%OUT%\check-%RUN%.json" echo Report: %OUT%\check-%RUN%.json
if "%RESULT%"=="0" echo Result: no known issue was found by the static check. This does not prove the whole game works.
if "%RESULT%"=="2" echo Result: issues were found. The lines above show the file and line number.
if not "%RESULT%"=="0" if not "%RESULT%"=="2" echo PyEmuera stopped (exit code %RESULT%). Read the message above. See HOW_TO_USE_ja.txt, section 9.
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
rem Resolve the selected Python executable via the launcher, including .cmd shims.
rem Call the executable directly to avoid re-expanding user arguments.
set "PYEXE="
set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"
where py >nul 2>nul
if errorlevel 1 goto trypython
for /f "delims=" %%P in ('call py -3 -X utf8 -c "import sys; print(sys.executable if sys.version_info.__ge__((3, 10)) else None)" ^<nul 2^>nul') do set "PYEXE=%%P"
if defined PYEXE if exist "%PYEXE%" exit /b 0
set "PYEXE="
:trypython
where python >nul 2>nul
if errorlevel 1 exit /b 0
for /f "delims=" %%P in ('call python -X utf8 -c "import sys; print(sys.executable if sys.version_info.__ge__((3, 10)) else None)" ^<nul 2^>nul') do set "PYEXE=%%P"
if defined PYEXE if exist "%PYEXE%" exit /b 0
set "PYEXE="
exit /b 0
