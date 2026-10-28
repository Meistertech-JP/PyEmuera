@echo off
rem Play with diagnostic reports. Drag a variant folder onto this file.
rem Reports are written to the "reports" folder. They can include file names, function names
rem and error messages from the game. Review them before sharing.
setlocal DisableDelayedExpansion
set "PYZ=%~dp0PyEmuera.pyz"
if not exist "%PYZ%" goto nopyz
call :findpython
if not defined PYEXE goto nopython
set "OUT=%~dp0reports"
rem Reserve a new directory. An old report can never be counted as this run's output.
rem mkdir succeeds only when the directory did not already exist (including races).
set "ATTEMPTS=0"
:reserve
set /a ATTEMPTS+=1 >nul
set "RUNOUT=%OUT%\run-%RANDOM%-%RANDOM%-%RANDOM%"
mkdir "%RUNOUT%" >nul 2>nul
if not errorlevel 1 goto reserved
if %ATTEMPTS% LSS 16 goto reserve
echo No reports were generated. A new report folder could not be created in: "%OUT%"
echo Check write permission and whether a file named reports blocks the folder.
call :wait
exit /b 1
:reserved
"%PYEXE%" "%PYZ%" %* --report "%RUNOUT%\check.json" --session-report "%RUNOUT%\session.json" --error-report "%RUNOUT%\error.json"
set "RESULT=%ERRORLEVEL%"
set "REPORTS=0"
set "INVALID=0"
set "GOT_check="
set "GOT_session="
set "GOT_error="
set "BAD_check="
set "BAD_session="
set "BAD_error="
for %%F in (check session error) do call :inspectreport %%F
echo.
if not "%INVALID%"=="0" goto invalidreports
if "%REPORTS%"=="0" goto noreports
rem An error report is conditional: normal, check-only and interrupted runs may omit it.
if not defined GOT_check goto partialreports
if not defined GOT_session goto partialreports
if defined GOT_error goto completereports
if "%RESULT%"=="0" goto completereports
if "%RESULT%"=="2" goto completereports
if "%RESULT%"=="130" goto completereports
:partialreports
echo Only some reports were generated in this run: "%RUNOUT%"
goto listreports
:completereports
echo Reports were written to: "%RUNOUT%"
echo Check and session reports are present. An error report is written only when applicable.
:listreports
for %%F in (check session error) do if defined GOT_%%F echo   %%F.json
goto outcome
:invalidreports
echo Incomplete or unreadable reports were found in this run: "%RUNOUT%"
if not "%REPORTS%"=="0" echo Only some reports were generated in this run: "%RUNOUT%"
for %%F in (check session error) do if defined BAD_%%F echo Incomplete or unreadable JSON object: %%F.json
if "%REPORTS%"=="0" echo No complete JSON object reports were generated in this run.
if not "%REPORTS%"=="0" echo Complete JSON object reports from this run:
goto listreports
:noreports
echo No reports were generated in this run.
:outcome
if "%RESULT%"=="0" echo PyEmuera finished normally (exit code 0).
if not "%RESULT%"=="0" echo PyEmuera stopped (exit code %RESULT%). Read the message above. See HOW_TO_USE_ja.txt, section 10.
call :wait
exit /b %RESULT%

:inspectreport
rem Parse the entire UTF-8 file; empty, truncated, unreadable and non-object JSON
rem outputs are never advertised as complete. Keep the engine RESULT untouched.
if not exist "%RUNOUT%\%~1.json" exit /b 0
"%PYEXE%" -c "import json,sys; obj=json.loads(open(sys.argv[1],encoding='utf-8').read()); sys.exit(0 if isinstance(obj,dict) else 1)" "%RUNOUT%\%~1.json" <nul >nul 2>nul
if errorlevel 1 goto invalidreport
set "GOT_%~1=1"
set /a REPORTS+=1 >nul
exit /b 0
:invalidreport
set "BAD_%~1=1"
set /a INVALID+=1 >nul
exit /b 0

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
