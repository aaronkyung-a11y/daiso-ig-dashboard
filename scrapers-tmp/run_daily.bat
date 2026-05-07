@echo off
chcp 65001 > nul
setlocal

REM 작업 디렉토리 = 이 .bat 파일이 있는 위치
cd /d "%~dp0"

REM 로그 디렉토리 + 파일
set LOG_DIR=%~dp0..\logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set TS=%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%
set TS=%TS: =0%
set LOG_FILE=%LOG_DIR%\run_daily_%TS%.log

echo [%date% %time%] === 다이소 모니터 일일 실행 === > "%LOG_FILE%"
echo. >> "%LOG_FILE%"
echo IG 크롤링은 Cowork scheduled-task가 별도 처리 (daiso-ig-daily-crawl, 매일 09:15) >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

REM 1. 다이소 스크래퍼
echo [%date% %time%] (1/4) daiso_scraper.py --sheets >> "%LOG_FILE%"
py daiso_scraper.py --sheets >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo   ! 실패 (errorlevel %errorlevel%) >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

REM 2. YT 크롤러 (API 키 없으면 자동 skip)
echo [%date% %time%] (2/4) yt_crawler.py >> "%LOG_FILE%"
py yt_crawler.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo   ! YT 실패 (API 키 미설정 가능) >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

REM 3. 인플루언서 평가
echo [%date% %time%] (3/4) influencer_eval.py >> "%LOG_FILE%"
py influencer_eval.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo   ! 실패 >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

REM 4. 대시보드 빌드
echo [%date% %time%] (4/5) build_dashboard.py >> "%LOG_FILE%"
py build_dashboard.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo   ! 실패 >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

REM 5. GitHub Pages 자동 push
echo [%date% %time%] (5/6) push_dashboard.py >> "%LOG_FILE%"
py push_dashboard.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo   ! GitHub push 실패 (PAT 미설정 가능) >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

REM 6. 평가 큐 자동 push (미평가 인플루언서 → eval-queue label issues)
echo [%date% %time%] (6/6) push_eval_queue.py >> "%LOG_FILE%"
py push_eval_queue.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo   ! 평가 큐 push 실패 >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

echo [%date% %time%] === 완료 === >> "%LOG_FILE%"

REM 30일 이상 된 로그 정리
forfiles /p "%LOG_DIR%" /m run_daily_*.log /d -30 /c "cmd /c del @path" 2>nul

endlocal
