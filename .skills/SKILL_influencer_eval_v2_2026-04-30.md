# influencer-eval-thrice-daily — v2 SKILL.md (2026-04-30)

> ★ 적용 방법 (이 세션 종료 후 새 세션에서):
> "scheduled-tasks: influencer-eval-thrice-daily 의 prompt 를 이 파일 본문(아래 `## 실행 스케줄`부터 끝까지)으로 갱신해줘"
>
> 변경 요약 (v1 → v2):
> 1. 큐 소스에 **Google Form CSV (A-1-c)** 추가
> 2. **brand_fit 로직 v2** — 다이소 미언급 감점 폐지, 뷰티 토픽 강도 1차 기준
> 3. **retailer_focus** 필드 신설 (daiso/olive_young/mixed/beauty_general/our_brand/off_topic)
> 4. **STEP B-Light** 신설 — 매 실행마다 가장 오래된 2건 자동 재분석
> 5. IG 샘플 사이즈 → 로그인 18~24, 로그아웃 12 cap 명시
> 6. SPA 캐시 cross-contamination 방지: code 매칭 기반 강건한 추출

---

너는 인플루언서 평가 자동화 작업을 실행한다. 작업 정의는 아래 SKILL.md에 있다.

## 실행 스케줄 (★ SKILL.md 본문보다 우선 ★)

- **평일(월~금) 09:00, 14:00, 17:00** — 하루 3회 실행 (cron: `0 9,14,17 * * 1-5`)
- **매 실행마다 STEP A (Queue), STEP B-Light (가장 오래된 2건 자동 재분석), STEP C (인덱스/HTML), STEP D (라이브 검증), STEP E (보고)** 는 반드시 실행
- **STEP B (Watchlist 풀 재분석)** 은 **월요일 09:00 실행 시에만 추가**

## 실행 시각 판별
```bash
TZ=Asia/Seoul date +"%u %H"
```
`요일==1 AND 시==09` 인 경우만 STEP B 풀 재분석. 그 외에는 STEP B SKIP, STEP B-Light는 항상 실행.

## 작업 정의 (SKILL.md 본문)

# influencer-eval (작업 정의)

## 자격 증명
- GitHub PAT: `${GITHUB_PAT_DAISO_IG_DASHBOARD}`
- 리포: `aaronkyung-a11y/daiso-ig-dashboard`
- 라이브: https://aaronkyung-a11y.github.io/daiso-ig-dashboard/influencer-eval.html

## 데이터 위치 (GitHub repo)
- `/influencers/_index.json`, `_watchlist.json`, `_queue.txt`, `{platform}_{username}.json`
- `/influencer-eval.html` 인라인 마커: `// INFLUENCER_DATA_BEGIN/END`

## 점수 산출 (★ v2 brand_fit 로직 ★)
```
total = ER점수 × 0.50 + 브랜드적합도 × 0.25 + 일관성점수 × 0.15 + 팔로워규모 × 0.10
```
- **ER점수**: ≥10%:100 / 5~10%:90 / 3~5%:80 / 1~3%:60 / <1%:40 (IG ER>100% viral은 100 cap)
- **브랜드 적합도** (★ v2: 다이소 미언급 감점 없음 ★):
  - 뷰티/화장품 토픽 강도가 1차 기준 (캡션·해시태그·bio):
    - 강함(키워드 8건+): 90점 베이스
    - 중간(3~7건): 75점 베이스
    - 약함(1~2건): 60점 베이스
    - 무관(0건): 25점 베이스
  - 우리 브랜드(더랩바이블랑두) 직접 언급 시 **+20 보너스** (cap 100)
- **retailer_focus** 필드 (별도, 점수와 무관): `daiso` / `olive_young` / `mixed` / `beauty_general` / `our_brand` / `off_topic`
- **업로드 일관성** (30일 게시물 수): ≥10:100 / 5~10:80 / 2~5:60 / <2:40
- **팔로워 규모**: ≥100k:100 / 10k~100k:80 / 1k~10k:60 / <1k:40

## 실행 흐름
1. STEP A: Queue 처리 — 매 실행
2. STEP B: Watchlist 풀 재분석 — 월 09시에만
3. ★ STEP B-Light: 가장 오래된 2건 재분석 — 월 09시 제외 매 실행
4. STEP C: index/HTML 갱신 — 매 실행
5. STEP D: 라이브 검증 — 매 실행
6. STEP E: 보고 — 매 실행

---

# STEP A — Queue 처리

## A-1. 큐 가져오기 (★ 세 소스 모두 ★)

### A-1-a. GitHub Issues (`eval-queue` 라벨)
```bash
PAT="${GITHUB_PAT_DAISO_IG_DASHBOARD}"
REPO="aaronkyung-a11y/daiso-ig-dashboard"
curl -sS -H "Authorization: token $PAT" \
  "https://api.github.com/repos/$REPO/issues?state=open&labels=eval-queue&per_page=50" > /tmp/issues.json
```

### A-1-b. _queue.txt (백업/수동 큐)
```bash
curl -sS -H "Authorization: token $PAT" -H "Accept: application/vnd.github.v3.raw" \
  "https://api.github.com/repos/$REPO/contents/influencers/_queue.txt?ref=main" > /tmp/queue.txt
```

### ★ A-1-c. Google Form 응답 시트 (★ v2 추가 ★)
```bash
CSV_URL='https://docs.google.com/spreadsheets/d/e/2PACX-1vTgag82A2UQN9fDaxWsjTghZSnYoUbflo1e2QM6upF3n3WKvxFCJz8JCDIvnpnxj6yNhgsVJJSHy6rU/pub?output=csv'
curl -sSL "$CSV_URL" > /tmp/form_responses.csv
```
- **dedup**: 같은 URL 여러 번 제출되면 1회만 분석
- **이미 분석 완료된 계정 SKIP**: per-account JSON 파일 존재하면 신규 분석 SKIP (rolling refresh로 갱신)
- Form은 append-only — 큐 비우기 불가, JSON 파일 존재로 자동 ✓ 처리

## A-2. URL → platform + username 파싱

## A-3. 분석 (IG)
- **로그아웃 검출** (sessionid 쿠키 부재 시): "⚠️ IG 로그아웃 — 샘플 12개 제한" 보고에 명시
- **샘플 사이즈**: 로그인 시 18~24, 로그아웃 시 12 cap
- **5초 throttle** per reel
- **★ SPA 캐시 cross-contamination 방지 — code 기반 강건한 추출 ★**:
```js
const code = location.pathname.match(/reel\/([A-Za-z0-9_-]+)/)?.[1];
const s = Array.from(document.querySelectorAll('script')).map(x=>x.textContent||'').join('\n');
const idx = s.indexOf(`"code":"${code}"`);
const block = idx >= 0 ? s.substring(Math.max(0, idx-1500), idx+2500) : '';
const like = (block.match(/"like_count":(\d+)/) || [])[1];
const cm = (block.match(/"comment_count":(\d+)/) || [])[1];
const taken = (block.match(/"taken_at":(\d+)/) || [])[1];
const cap = (block.match(/"caption":\{[^}]*?"text":"([^"]{0,500})"/) || [])[1] || '';
```

### ★ A-3-d. 캡션 키워드 분석 (★ v2 brand_fit + retailer_focus 산출 ★)
```python
captions_blob = ' '.join([r['caption'] for r in reels]).lower()
daiso_count = captions_blob.count('다이소') + captions_blob.count('daiso')
oy_count = captions_blob.count('올리브영') + captions_blob.count('올영') + captions_blob.count('oliveyoung')
beauty_keywords = ['메이크업','쿠션','틴트','립','뷰티','메이크','루틴','화장','스킨케어','베이스']
beauty_count = sum(captions_blob.count(k) for k in beauty_keywords)
labrang_present = '더랩바이블랑두' in captions_blob or '블랑두' in captions_blob

if beauty_count >= 8: bf = 90
elif beauty_count >= 3: bf = 75
elif beauty_count >= 1: bf = 60
else: bf = 25
if labrang_present: bf = min(100, bf + 20)

if labrang_present: retailer_focus = 'our_brand'
elif daiso_count > oy_count * 1.2: retailer_focus = 'daiso'
elif oy_count > daiso_count * 1.2: retailer_focus = 'olive_young'
elif daiso_count + oy_count > 0: retailer_focus = 'mixed'
elif beauty_count > 0: retailer_focus = 'beauty_general'
else: retailer_focus = 'off_topic'
```

## A-4. 분석 (YouTube — yt-dlp)
- 샘플: 30일 내 영상 (없으면 최근 18~20개)
- ER(YT) = avg_likes / avg_views
- 키워드 분석은 title 기반

## A-5. 점수 산출 + JSON 저장
**필수 필드 (v2)**: + `retailer_focus`, `retailer_signal`
동일 username 재분석 시 history[] push (최근 26개)

## A-6. Queue 비우기
- A-6-a (Issues): 처리 완료 close + 댓글
- A-6-b (_queue.txt): 처리 완료 URL 삭제, 실패는 `# FAILED YYYY-MM-DD:` 주석
- A-6-c (Form): append-only, JSON 파일 존재로 자동 ✓ 처리

---

# STEP B — Watchlist 풀 재분석 (★ 월요일 09시에만 ★)
SKIP 시 보고에 "STEP B SKIPPED (not Mon 09:00)" 명시.

---

# ★ STEP B-Light — Rolling Refresh (★ 월 09시 제외 매 실행 ★)

## B-Light-1. 가장 오래된 2건 선정
```python
import json
from pathlib import Path
all_jsons = []
for fp in Path('/tmp/influencers').glob('*.json'):
    if fp.name.startswith('_'): continue
    d = json.loads(fp.read_text())
    all_jsons.append((d.get('evaluated_at',''), fp))
all_jsons.sort()
oldest_2 = [fp for _, fp in all_jsons[:2]]
```
신규 분석된 계정 (이번 STEP A에서 처리된 계정) 후보 제외.

## B-Light-2. 재분석
선정된 2건에 대해 STEP A-3 (IG) 또는 A-4 (YT) 동일 분석 → history[] push.

## B-Light-3. 보고
"STEP B-Light: {계정1}, {계정2} 재분석 완료. 점수 변동: 이전→이후."

이 룰로 9개 계정 기준 약 1.5일에 한 바퀴 자동 갱신 (3회/일 × 2건 = 6건/일).

---

# STEP C — _index.json + influencer-eval.html 갱신
- C-1. _index.json 재생성 (★ retailer_focus 요약 필드 포함 ★)
- C-2. HTML 인라인 INFLUENCER_DATA 갱신
- C-3. Watchlist 신규 계정 자동 추가

---

# STEP D — 라이브 검증 (★ 매 실행 필수 ★)
CDN 30~45초 대기 후 Chrome 확장 검증. 통과 기준: hasData==='object', count>0, lastUpd 가 이번 실행 시각, 첫 row 렌더. 실패 시 30초 대기 후 최대 3회 재시도.

---

# STEP E — 보고
1. 실행 모드 (월 09시 풀 / 평일 큐+B-Light)
2. 신규 분석 (큐 3소스 합산)
3. **STEP B-Light**: 재분석 2건의 점수 변동
4. STEP B (월 09시): ±10 이상 변동 계정
5. 점수 변동 알림 (S→A 강등, 새 S 진입, ER 50%+ 하락)
6. 새 협업 후보 추천 (S등급 + 더랩바이블랑두 명시)
7. **★ retailer_focus 분포 (v2 추가) ★**: daiso/olive_young/mixed/beauty_general/our_brand/off_topic 카운트
8. 커밋 SHA
9. STEP D 검증 결과
10. **추정/실측 구분**: brand_fit_score, posts_last_30d (taken_at 부분만 잡힌 경우) → 추정 명시

---

## 사고 방지 체크리스트
- [ ] STEP B 풀 재분석은 월 09시만, STEP B-Light는 그 외 항상
- [ ] IG 로그인 상태 확인 (sessionid 쿠키)
- [ ] 큐 3소스 모두 읽기: Issues + _queue.txt + Form CSV
- [ ] **★ 변수명 `INFLUENCER_DATA` 유지 ★**
- [ ] **★ 마커 `// INFLUENCER_DATA_BEGIN/END` 유지 ★**
- [ ] **★ 점수 가중치 변경 금지 ★**
- [ ] **★ v2 brand_fit: 다이소 미언급 = 감점 사유 아님 ★**
- [ ] **★ retailer_focus 필드 산출·저장 ★**
- [ ] IG reel 5초 throttle, code 기반 강건한 추출
- [ ] IG 샘플: 로그인 18~24, 로그아웃 12 cap
- [ ] Form dedup + 이미 JSON 존재 SKIP
- [ ] 동일 계정 재분석 시 history[] push (최근 26개)
- [ ] STEP D 검증 통과
- [ ] 추정 수치는 보고에 "추정" 명시
