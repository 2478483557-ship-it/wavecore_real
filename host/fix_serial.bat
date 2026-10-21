@echo off
REM ============================================================
REM  WaveCore  serial port repair  (no reboot needed)
REM  Right click -> Run as administrator
REM
REM  Why: the CH340 on the board is powered from the USB cable,
REM  not from the board supply. Turning the board off does not
REM  re-enumerate the USB device, so a state left over from the
REM  power surge sticks until the cable is unplugged or Windows
REM  re-enumerates. This script forces that re-enumeration.
REM ============================================================
setlocal

net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Need administrator rights.
    echo   Right click this file, choose "Run as administrator".
    echo.
    pause
    exit /b 1
)

echo.
echo   [1/3] Listing CH340 devices ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d = @(Get-PnpDevice -Class Ports | Where-Object { $_.FriendlyName -like '*CH340*' -and $_.Present }); if ($d.Count -eq 0) { Write-Host '  no CH340 present - is the USB cable connected?'; exit 1 }; foreach ($x in $d) { Write-Host ('  ' + $x.FriendlyName + '    status=' + $x.Status) }"

if errorlevel 1 (
    echo.
    pause
    exit /b 1
)

echo.
echo   [2/3] Restarting the device stack ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d = @(Get-PnpDevice -Class Ports | Where-Object { $_.FriendlyName -like '*CH340*' -and $_.Present }); foreach ($x in $d) { pnputil /restart-device $x.InstanceId 2>&1 | Out-Null; Write-Host ('  restarted ' + $x.FriendlyName) }; Start-Sleep -Seconds 4"

echo.
echo   [3/3] Verifying at 460800 8N1 ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok = $false; $d = @(Get-PnpDevice -Class Ports | Where-Object { $_.FriendlyName -like '*CH340*' -and $_.Present }); foreach ($x in $d) { $m = [regex]::Match($x.FriendlyName, 'COM\d+'); if (-not $m.Success) { continue }; try { $p = New-Object System.IO.Ports.SerialPort($m.Value, 460800); $p.Open(); $p.Close(); Write-Host ('  ' + $m.Value + '   OK'); $ok = $true } catch { Write-Host ('  ' + $m.Value + '   FAILED'); Write-Host ('    ' + $_.Exception.Message) } }; Write-Host ''; if ($ok) { Write-Host '  Serial port is usable again.' } else { Write-Host '  Still broken. Unplug the USB cable, wait 5 seconds, plug it'; Write-Host '  back in, then run this script again.' }"

echo.
pause
