@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

if not exist "runtime\logs" mkdir "runtime\logs" >nul 2>&1
set "LAUNCH_LOG=%~dp0runtime\logs\launcher_latest.log"
if /i not "%~1"=="/elevated" >> "%LAUNCH_LOG%" echo.
call :launcher_log "Baslatma istendi. Parametre=%~1"

rem net session, Server hizmetine de bagli oldugu icin guvenilir bir yonetici testi degildir.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$id=[Security.Principal.WindowsIdentity]::GetCurrent(); $principal=New-Object Security.Principal.WindowsPrincipal($id); if($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){exit 0}else{exit 1}" >nul 2>&1
if not errorlevel 1 goto elevated_ready

if /i "%~1"=="/elevated" (
    call :launcher_log "HATA: Yukseltilmis baslatma yapildi ancak yonetici yetkisi alinamadi."
    call :show_error "PHANTOM yonetici yetkisi alamadi. launcher_latest.log dosyasini kontrol edin."
    exit /b 1
)

call :launcher_log "Windows yonetici izni isteniyor."
set "PHANTOM_BAT_PATH=%~f0"
set "PHANTOM_BAT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $q=[char]34; $argLine='/d /c '+$q+$q+$env:PHANTOM_BAT_PATH+$q+' /elevated'+$q; Start-Process -FilePath $env:ComSpec -ArgumentList $argLine -WorkingDirectory $env:PHANTOM_BAT_DIR -Verb RunAs" >> "%LAUNCH_LOG%" 2>&1
if errorlevel 1 (
    call :launcher_log "HATA: Yonetici izni penceresi acilamadi veya izin reddedildi."
    call :show_error "PHANTOM baslatilamadi. Yonetici izni reddedildi veya Windows izin penceresi acilamadi."
    exit /b 1
)
call :launcher_log "Yukseltilmis PHANTOM baslaticisi gonderildi; ilk pencere kapaniyor."
exit /b 0

:elevated_ready
call :launcher_log "Yonetici yetkisi dogrulandi; on kontroller basliyor."

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "VENV_PYW=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%VENV_PY%" (
    call :launcher_log "HATA: Sanal ortam Python dosyasi bulunamadi."
    call :show_error "PHANTOM Python ortami bulunamadi. Once kurulum.bat dosyasini calistirin."
    exit /b 1
)
if not exist "%VENV_PYW%" set "VENV_PYW=%VENV_PY%"

set "PYTHONUTF8=1"
"%VENV_PY%" -c "import sys" >nul 2>&1
if errorlevel 1 (
    call :launcher_log "HATA: Sanal ortam Python dosyasi calistirilamadi."
    call :show_error "PHANTOM Python ortami acilamadi. Once kurulum.bat dosyasini calistirin."
    exit /b 1
)
call :launcher_log "Python ortami hazir; agir kutuphaneler uygulama icinde yuklenecek."

set "PHANTOM_GUI_LAUNCH=1"
set "PHANTOM_ENTRY=%~dp0phantom_supervisor.py"
set "PHANTOM_ROOT=%~dp0"
call :launcher_log "GUI sureci baslatiliyor: %VENV_PYW%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $q=[char]34; $entryArg=$q+$env:PHANTOM_ENTRY+$q; $p=Start-Process -FilePath $env:VENV_PYW -ArgumentList $entryArg -WorkingDirectory $env:PHANTOM_ROOT -WindowStyle Hidden -PassThru; Write-Output ('['+(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')+'] GUI PID='+$p.Id); Start-Sleep -Seconds 12; if($p.HasExited){Write-Output ('['+(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')+'] HATA: GUI sureci erken kapandi. Cikis kodu='+$p.ExitCode); exit 1}; Write-Output ('['+(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')+'] GUI sureci 12 saniye sonra calisiyor.')" >> "%LAUNCH_LOG%" 2>&1
if errorlevel 1 (
    call :launcher_log "HATA: GUI sureci baslatilamadi veya erken kapandi."
    call :show_error "PHANTOM penceresi baslatilamadi. Ayrinti: runtime\logs\launcher_latest.log"
    exit /b 1
)
call :launcher_log "GUI sureci calisiyor; baslatici tamamlandi."
exit /b 0

:launcher_log
>> "%LAUNCH_LOG%" echo [%date% %time%] %~1
exit /b 0

:show_error
set "PHANTOM_LAUNCH_ERROR=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; [void][System.Windows.Forms.MessageBox]::Show($env:PHANTOM_LAUNCH_ERROR,'PHANTOM baslatma hatasi',[System.Windows.Forms.MessageBoxButtons]::OK,[System.Windows.Forms.MessageBoxIcon]::Error)" >nul 2>&1
exit /b 0
