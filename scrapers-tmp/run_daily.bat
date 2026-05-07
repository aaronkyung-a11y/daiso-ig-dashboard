@echo off
setlocal
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"

set "LOG_DIR=%~dp0..\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "TS=%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%"
set "TS=%TS: =0%"
set "LOG_FILE=%LOG_DIR%\run_daily_%TS%.log"

echo [%date% %time%] === Daiso Monitor Daily Run === > "%LOG_FILE%"
echo. >> "%LOG_FILE%"
echo IG crawling handled by Cowork scheduled-task (daiso-ig-daily-crawl, 09:24) >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

REM 1. Daiso scraper
echo [%date% %time%] (1/6) daiso_scraper.py --sheets >> "%LOG_FILE%"
py daiso_scraper.py --sheets >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo   ! FAILED (errorlevel %errorlevel%) >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

REM 2. YouTube crawler
echo [%date% %time%] (2/6) yt_crawler.py >> "%LOG_FILE%"
py yt_crawler.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo   ! YT FAILED (API key missing?) >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

REM 3. Influencer eval
echo [%date% %time%] (3/6) influencer_eval.py >> "%LOG_FILE%"
py influencer_eval.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo   ! FAILED >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

REM 4. Build dashboard
echo [%date% %time%] (4/6) build_dashboard.py >> "%LOG_FILE%"
py build_dashboard.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo   ! FAILED >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

REM 5. Push dashboard.html to GitHub Pages
echo [%date% %time%] (5/6) push_dashboard.py >> "%LOG_FILE%"
py push_dashboard.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo   ! GitHub push FAILED (PAT?) >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

REM 6. Push new influencers to eval queue (Google Form)
echo [%date% %time%] (6/6) push_eval_queue.py >> "%LOG_FILE%"
py push_eval_queue.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo   ! Eval queue push FAILED >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

echo [%date% %time%] === DONE === >> "%LOG_FILE%"

REM Cleanup logs older than 30 days
forfiles /p "%LOG_DIR%" /m run_daily_*.log /d -30 /c "cmd /c del @path" 2>nul

endlocal
