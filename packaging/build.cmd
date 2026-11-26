@echo off
rem Build the folder, then the installer. Needs PyInstaller (pip install pyinstaller) and Inno Setup 6.
rem Inno Setup installed per user lands in %LOCALAPPDATA%\Programs\Inno Setup 6; this finds it there.
setlocal
cd /d "%~dp0.."
set PY=.venv\Scripts\python.exe
set ISCC=iscc
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
for /f "delims=" %%v in ('%PY% -c "import excmp; print(excmp.__version__)"') do set VER=%%v
rem The external tools the installer carries (7-Zip, Precomp, zpaqfranz, FLAC, balrogg), checked against their pins.
rem Offline when toolsin is complete; downloads only what is missing.
%PY% packaging\stage_tools.py || exit /b 1
%PY% -m PyInstaller --noconfirm --clean packaging\ExtremeCompressor.spec || exit /b 1
%ISCC% /DAppVersion=%VER% packaging\installer.iss || exit /b 1
echo built dist\ExtremeCompressor-%VER%-setup.exe
