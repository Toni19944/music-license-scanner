@echo off

rem ============================================================
rem  Music License Scanner - One-Click Runner
rem  Edit the lines below to customize, then save and double-click
rem ============================================================

rem Path to your music folder
set MUSIC_FOLDER=F:\Music

rem Subfolders to exclude (comma-separated folder names, no spaces between)
rem Example: set EXCLUDE=Podcasts,Audiobooks,SFX,Temp
rem Leave blank to scan everything
set EXCLUDE=

rem Path to the script - only change if you moved it
set SCRIPT=music_license_scanner.py

rem ============================================================

echo.
echo  Music License Scanner
echo  ----------------------
echo  Scanning:  %MUSIC_FOLDER%
if not "%EXCLUDE%"=="" echo  Excluding: %EXCLUDE%
echo.

if "%EXCLUDE%"=="" (
    python "%SCRIPT%" "%MUSIC_FOLDER%"
) else (
    python "%SCRIPT%" "%MUSIC_FOLDER%" --exclude "%EXCLUDE%"
)

echo.
echo  Done! Open music_license_report.csv to see results.
echo  Tip: Filter the safe_to_use column in Excel for quick results.
pause
