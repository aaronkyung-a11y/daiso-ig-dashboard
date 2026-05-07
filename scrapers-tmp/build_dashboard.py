"""
다이소 뷰티 모니터링 대시보드 빌더

매일 데이터 모아서 단일 HTML 파일 generate.
출력: G:\\내 드라이브\\AI\\daiso-monitor\\dashboard.html

입력 데이터:
- logs/daiso_YYYY-MM-DD.json (오늘의 다이소 Top 30)
- logs/ig_reel_store.json (IG 누적 reel)
- logs/yt_YYYY-MM-DD.json (오늘의 YT 영상)
- logs/influencers_YYYY-MM-DD.json (오늘의 인플루언서 점수)

생성된 HTML 특징:
- Hero 통계 카드
- 다이소 Top 30 표 (비뷰티 표시, 순위변화)
- 핫 컨텐츠 (조회수/좋아요 내림차순, IG/YT 통합)
- 인플루언서 Top 점수 (모두 클릭 가능)
- 우선 섭외 추천 Top 3
- JS 필터/검색/정렬

실행:
    py build_dashboard.py
"""

import argparse
import html
import json
import ssl
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
LOGS_DIR = BASE_DIR / "logs"
OUTPUT_PATH = BASE_DIR / "dashboard.html"


def safe_load(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def esc(s):
    return html.escape(str(s)) if s is not None else ""


def _latest(prefix: str):
    """logs/{prefix}_*.json 중 가장 최근 (파일명 기준 내림차순)."""
    files = sorted(LOGS_DIR.glob(f"{prefix}_*.json"), reverse=True)
    return safe_load(files[0]) if files else None


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl._create_unverified_context()


_SSL_CTX = _ssl_ctx()


def _fetch_eval_index():
    """기존 influencer-eval 시스템의 _index.json 라이브 fetch."""
    url = "https://raw.githubusercontent.com/aaronkyung-a11y/daiso-ig-dashboard/main/influencers/_index.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "daiso-monitor/1.0"})
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[WARN] influencer-eval _index.json fetch 실패: {e}")
        return None


def build():
    today = datetime.now().strftime("%Y-%m-%d")
    daiso = _latest("daiso") or []
    ig_store = safe_load(LOGS_DIR / "ig_reel_store.json") or []
    yt = _latest("yt") or []
    influencers = _latest("influencers") or []

    # 데이터 출처 날짜 (가장 최근 daiso 파일명에서 추출)
    daiso_files = sorted(LOGS_DIR.glob("daiso_*.json"), reverse=True)
    daiso_date = daiso_files[0].stem.replace("daiso_", "") if daiso_files else today

    # 기존 influencer-eval 시스템 데이터 fetch
    eval_index = _fetch_eval_index()
    eval_records = eval_index.get("records", []) if eval_index else []
    eval_by_username = {r.get("username", "").lower().lstrip("@"): r for r in eval_records}
    eval_count = len(eval_records)
    eval_grade_dist = eval_index.get("retailer_focus_summary", {}) if eval_index else {}

    # 30일 통과 IG만
    cutoff_30d = (datetime.now().replace(microsecond=0) - __import__("datetime").timedelta(days=30)).strftime("%Y-%m-%d")
    ig_30d = [r for r in ig_store if (r.get("date") or "1900-01-01") >= cutoff_30d]

    # 통계
    beauty_count = sum(1 for p in daiso if p.get("is_beauty"))
    new_entry = sum(1 for p in daiso if p.get("진입구분", "") == "NEW")  # 추후 어제 데이터 비교

    # 핫 컨텐츠 통합 (IG + YT)
    contents = []
    for r in ig_30d:
        contents.append({
            "platform": "Instagram",
            "platform_class": "ig",
            "title": (r.get("caption") or "")[:60],
            "user": r.get("user") or "?",
            "metric": r.get("likes") or 0,
            "metric_label": "likes",
            "comments": r.get("comments") or 0,
            "date": r.get("date") or "",
            "url": r.get("url") or "",
            "user_url": f"https://www.instagram.com/{(r.get('user') or '').lstrip('@')}/" if r.get("user") else "#",
            "keyword": r.get("brand_keyword") or "",
            "daiso": r.get("mentions_daiso", False),
        })
    for v in yt:
        contents.append({
            "platform": "YouTube",
            "platform_class": "yt",
            "title": (v.get("title") or "")[:60],
            "user": v.get("channelName") or "?",
            "metric": v.get("views") or 0,
            "metric_label": "views",
            "comments": v.get("comments") or 0,
            "date": v.get("publishedAt") or "",
            "url": v.get("url") or "",
            "user_url": f"https://www.youtube.com/channel/{v.get('channelId')}" if v.get("channelId") else "#",
            "keyword": v.get("brand_keyword") or "",
            "daiso": v.get("mentions_daiso", False),
        })
    contents_sorted = sorted(contents, key=lambda c: c["metric"], reverse=True)

    # 우선 섭외 추천 (Top 3)
    outreach_top3 = [i for i in influencers if i.get("top_score", 0) > 0][:3]

    # === HTML 생성 ===
    daiso_rows_html = ""
    for p in daiso[:30]:
        beauty_badge = "" if p.get("is_beauty") else '<span class="badge non-beauty">비뷰티</span>'
        daiso_rows_html += f"""
        <tr data-beauty="{1 if p.get('is_beauty') else 0}">
          <td class="rank">{p.get('순위', '')}</td>
          <td>{esc(p.get('제품명', ''))[:50]} {beauty_badge}</td>
          <td class="num">{(p.get('가격') or 0):,}원</td>
          <td class="num">{esc(p.get('별점', ''))}</td>
          <td class="num">{esc(p.get('누적구매') or '-')}</td>
          <td><a href="{esc(p.get('다이소상세URL') or '#')}" target="_blank">상세 ↗</a></td>
        </tr>"""

    contents_rows_html = ""
    for c in contents_sorted[:20]:
        daiso_pill = '<span class="pill daiso">다이소</span>' if c["daiso"] else ""
        contents_rows_html += f"""
        <tr data-platform="{c['platform_class']}">
          <td><span class="platform-badge {c['platform_class']}">{c['platform']}</span></td>
          <td><a href="{esc(c['user_url'])}" target="_blank" class="user-link">@{esc(c['user'])} ↗</a></td>
          <td>{esc(c['title'])} {daiso_pill}</td>
          <td class="num bold">{c['metric']:,}</td>
          <td class="num">{c['comments']:,}</td>
          <td class="date">{esc(c['date'])}</td>
          <td><a href="{esc(c['url'])}" target="_blank">▶ 보기</a></td>
        </tr>"""

    influencers_rows_html = ""
    for i, inf in enumerate(influencers[:15], 1):
        is_ig = inf["platform"] == "instagram"
        name = inf.get("username") or inf.get("channel_name") or "?"
        platform_class = "ig" if is_ig else "yt"
        platform_label = "Instagram" if is_ig else "YouTube"
        if is_ig:
            metric = f"평균 likes {inf['avg_likes']:.0f}"
        else:
            metric = f"평균 views {int(inf.get('avg_views') or 0):,}"
        focus = inf.get("retailer_focus", "")
        focus_class = "daiso" if "daiso" in focus else "general"
        rising = inf.get("rising_score") or "—"
        rising_str = f"{rising:.3f}" if isinstance(rising, (int, float)) else rising
        # 기존 평가 매칭
        match_key = (inf.get("username") or inf.get("channel_name") or "").lower().lstrip("@")
        eval_match = eval_by_username.get(match_key)
        if eval_match:
            grade = eval_match.get("grade", "?")
            eval_badge = f'<span class="grade-badge grade-{grade}">정밀 {grade}</span>'
        else:
            eval_badge = '<span class="grade-badge grade-pending">미평가</span>'
        influencers_rows_html += f"""
        <tr>
          <td class="rank">{i}</td>
          <td><span class="platform-badge {platform_class}">{platform_label}</span></td>
          <td><a href="{esc(inf.get('profile_url') or '#')}" target="_blank" class="user-link">{esc(name)} ↗</a></td>
          <td class="num bold">{inf.get('top_score', 0):.3f}</td>
          <td>{eval_badge}</td>
          <td>{esc(metric)}</td>
          <td><span class="pill {focus_class}">{esc(focus)}</span></td>
          <td><a href="{esc(inf.get('latest_content_url') or '#')}" target="_blank">▶ 최근</a></td>
        </tr>"""

    outreach_cards_html = ""
    for i, o in enumerate(outreach_top3, 1):
        is_ig = o["platform"] == "instagram"
        name = o.get("username") or o.get("channel_name") or "?"
        reason_parts = []
        if o.get("retailer_focus", "").startswith("daiso"):
            reason_parts.append("다이소 카테고리 적합")
        if o.get("avg_likes", 0) > 1000 or o.get("avg_views", 0) > 100000:
            reason_parts.append("높은 도달")
        reason = " · ".join(reason_parts) or "잠재 후보"
        outreach_cards_html += f"""
        <div class="outreach-card">
          <div class="outreach-num">{i}</div>
          <div class="outreach-body">
            <div class="outreach-name">
              <a href="{esc(o.get('profile_url') or '#')}" target="_blank" class="user-link">{esc(name)} ↗</a>
              <span class="platform-badge {('ig' if is_ig else 'yt')}">{('Instagram' if is_ig else 'YouTube')}</span>
            </div>
            <div class="outreach-reason">{esc(reason)}</div>
          </div>
          <div class="outreach-score">{o.get('top_score', 0):.3f}</div>
        </div>"""

    # 페이지 HTML
    html_doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>다이소 뷰티 데일리 — {today}</title>
<link rel="stylesheet" as="style" crossorigin
      href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Pretendard Variable', 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
    background: #f6f7fb; color: #18181b; line-height: 1.55;
    padding: 24px 16px 64px;
    font-feature-settings: 'tnum';
    -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
    letter-spacing: -0.01em;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; }}

  .header {{
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
    color: white; padding: 28px 32px; border-radius: 16px;
    margin-bottom: 20px; position: relative; overflow: hidden;
  }}
  .header::after {{
    content: ''; position: absolute; right: -40px; top: -40px;
    width: 180px; height: 180px; background: rgba(255,255,255,0.08); border-radius: 50%;
  }}
  .header h1 {{ font-size: 26px; font-weight: 700; margin-bottom: 4px; letter-spacing: -0.02em; }}
  .header .subtitle {{ font-size: 13px; opacity: 0.9; }}

  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }}
  .stat {{ background: white; padding: 16px; border-radius: 12px; border: 1px solid #eee; }}
  .stat .label {{ font-size: 12px; color: #71717a; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; }}
  .stat .value {{ font-size: 26px; font-weight: 700; margin-top: 4px; letter-spacing: -0.02em; }}
  .stat .sub {{ font-size: 11px; color: #a1a1aa; margin-top: 4px; }}

  .section {{ background: white; border-radius: 14px; border: 1px solid #eee; margin-bottom: 20px; overflow: hidden; }}
  .section-head {{ padding: 14px 20px; border-bottom: 1px solid #f0f0f5; display: flex; justify-content: space-between; align-items: center; }}
  .section-head h2 {{ font-size: 16px; font-weight: 600; letter-spacing: -0.01em; }}
  .section-head .toolbar {{ display: flex; gap: 8px; align-items: center; }}
  .section-head input[type="text"] {{ padding: 6px 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 13px; width: 180px; }}
  .section-head select {{ padding: 6px 8px; border: 1px solid #ddd; border-radius: 6px; font-size: 13px; }}

  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  thead tr {{ background: #fafafa; font-size: 11px; color: #71717a; text-transform: uppercase; letter-spacing: 0.4px; }}
  th {{ padding: 10px 12px; text-align: left; font-weight: 600; }}
  td {{ padding: 10px 12px; border-top: 1px solid #f5f5f5; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.rank {{ font-weight: 700; }}
  td.bold {{ font-weight: 700; }}
  td.date {{ color: #71717a; font-size: 12px; }}
  tr:hover {{ background: #fafbff; }}

  a {{ color: #4f46e5; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .user-link {{ font-family: 'JetBrains Mono', 'SF Mono', 'Menlo', 'D2Coding', monospace; font-size: 12px; }}

  .platform-badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
  .platform-badge.ig {{ background: linear-gradient(45deg, #f59e0b, #ec4899); color: white; }}
  .platform-badge.yt {{ background: #fee2e2; color: #b91c1c; }}

  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; margin-left: 4px; }}
  .badge.non-beauty {{ background: #fef3c7; color: #92400e; }}

  .pill {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; margin-left: 4px; }}
  .pill.daiso {{ background: #dcfce7; color: #166534; }}
  .pill.general {{ background: #f3f4f6; color: #4b5563; }}

  .grade-badge {{ display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; min-width: 56px; text-align: center; }}
  .grade-S {{ background: #fef3c7; color: #92400e; border: 1px solid #f59e0b; }}
  .grade-A {{ background: #dcfce7; color: #166534; }}
  .grade-B {{ background: #dbeafe; color: #1e40af; }}
  .grade-C {{ background: #f3f4f6; color: #4b5563; }}
  .grade-D {{ background: #fee2e2; color: #991b1b; }}
  .grade-pending {{ background: #fafafa; color: #a1a1aa; border: 1px dashed #d4d4d8; }}

  .nav-bar {{ display: flex; gap: 12px; margin-bottom: 16px; }}
  .nav-bar a {{ padding: 8px 16px; background: white; border: 1px solid #e5e7eb; border-radius: 8px; font-size: 13px; font-weight: 500; color: #374151; }}
  .nav-bar a.active {{ background: #6366f1; color: white; border-color: #6366f1; }}

  .outreach-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; padding: 16px 20px; }}
  .outreach-card {{
    display: grid; grid-template-columns: 40px 1fr auto; gap: 12px; align-items: center;
    padding: 14px; background: #fafafa; border-radius: 10px; border-left: 3px solid #16a34a;
  }}
  .outreach-num {{ width: 36px; height: 36px; background: linear-gradient(135deg, #16a34a, #15803d); color: white; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 16px; font-weight: 700; }}
  .outreach-name {{ font-size: 13px; font-weight: 700; margin-bottom: 4px; }}
  .outreach-reason {{ font-size: 11px; color: #71717a; }}
  .outreach-score {{ background: #dcfce7; color: #15803d; padding: 6px 12px; border-radius: 6px; font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }}

  .footer {{ text-align: center; color: #a1a1aa; font-size: 12px; margin-top: 32px; padding: 16px; }}

  @media (max-width: 768px) {{
    .stats {{ grid-template-columns: 1fr 1fr; }}
    .outreach-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<div class="container">

  <div class="nav-bar">
    <a href="#" class="active">다이소 모니터 (자동 발견)</a>
    <a href="https://aaronkyung-a11y.github.io/daiso-ig-dashboard/influencer-eval.html">정밀 평가 시스템 ({eval_count}명)</a>
    <a href="https://aaronkyung-a11y.github.io/daiso-ig-dashboard/">기존 메인 대시보드</a>
  </div>

  <div class="header">
    <h1>다이소 뷰티 데일리</h1>
    <div class="subtitle">{today} 빌드 · 다이소 데이터 {daiso_date} 기준 · IG 누적 30일 · YT 30일</div>
  </div>

  <div class="stats">
    <div class="stat"><div class="label">다이소 Top 30 (뷰티)</div><div class="value">{beauty_count}</div><div class="sub">/ {len(daiso)}</div></div>
    <div class="stat"><div class="label">감지 IG 컨텐츠 (30일)</div><div class="value">{len(ig_30d)}</div><div class="sub">/ 누적 {len(ig_store)}</div></div>
    <div class="stat"><div class="label">YT 영상</div><div class="value">{len(yt)}</div><div class="sub">최근 30일</div></div>
    <div class="stat"><div class="label">평가된 인플루언서</div><div class="value">{len(influencers)}</div><div class="sub">Top 점수 산출</div></div>
  </div>

  <!-- 우선 섭외 -->
  <div class="section">
    <div class="section-head">
      <h2>오늘 우선 섭외 추천 Top 3</h2>
    </div>
    <div class="outreach-grid">
      {outreach_cards_html or '<p style="padding: 16px; color: #999;">데이터 누적 후 활성화</p>'}
    </div>
  </div>

  <!-- 인플루언서 -->
  <div class="section">
    <div class="section-head">
      <h2>인플루언서 Top 영향력</h2>
    </div>
    <table>
      <thead><tr><th>#</th><th>플랫폼</th><th>계정 (클릭→프로필)</th><th>Top 점수</th><th>정밀평가</th><th>평균 도달</th><th>분류</th><th>최근</th></tr></thead>
      <tbody>{influencers_rows_html or '<tr><td colspan="8" style="color:#999;text-align:center;padding:24px;">평가 데이터 없음</td></tr>'}</tbody>
    </table>
  </div>

  <!-- 핫 컨텐츠 -->
  <div class="section" id="content-section">
    <div class="section-head">
      <h2>핫 컨텐츠 (도달 내림차순, Top 20)</h2>
      <div class="toolbar">
        <input type="text" id="content-search" placeholder="제목·계정 검색" oninput="filterContents()">
        <select id="platform-filter" onchange="filterContents()">
          <option value="all">전체</option><option value="ig">Instagram</option><option value="yt">YouTube</option>
        </select>
      </div>
    </div>
    <table id="content-table">
      <thead><tr><th>플랫폼</th><th>계정</th><th>제목/캡션</th><th>도달</th><th>댓글</th><th>날짜</th><th>보기</th></tr></thead>
      <tbody>{contents_rows_html or '<tr><td colspan="7" style="color:#999;text-align:center;padding:24px;">컨텐츠 없음</td></tr>'}</tbody>
    </table>
  </div>

  <!-- 다이소 Top 30 -->
  <div class="section">
    <div class="section-head">
      <h2>다이소몰 일간 Top 30</h2>
      <div class="toolbar">
        <label style="font-size:12px;"><input type="checkbox" id="beauty-only" onchange="filterDaiso()" checked> 뷰티만</label>
      </div>
    </div>
    <table id="daiso-table">
      <thead><tr><th>순위</th><th>제품명</th><th>가격</th><th>별점</th><th>누적구매</th><th>다이소</th></tr></thead>
      <tbody>{daiso_rows_html or '<tr><td colspan="6" style="color:#999;text-align:center;padding:24px;">데이터 없음 — daiso_scraper.py 실행</td></tr>'}</tbody>
    </table>
  </div>

  <div class="footer">
    자동 빌드 · {today} · build_dashboard.py · 데이터 갱신: daiso_scraper / ig_crawler / yt_crawler / influencer_eval 매일 실행
  </div>
</div>

<script>
function filterContents() {{
  const q = document.getElementById('content-search').value.toLowerCase();
  const plat = document.getElementById('platform-filter').value;
  document.querySelectorAll('#content-table tbody tr').forEach(tr => {{
    const matchPlat = plat === 'all' || tr.dataset.platform === plat;
    const matchSearch = !q || tr.textContent.toLowerCase().includes(q);
    tr.style.display = (matchPlat && matchSearch) ? '' : 'none';
  }});
}}
function filterDaiso() {{
  const beautyOnly = document.getElementById('beauty-only').checked;
  document.querySelectorAll('#daiso-table tbody tr').forEach(tr => {{
    tr.style.display = (!beautyOnly || tr.dataset.beauty === '1') ? '' : 'none';
  }});
}}
filterDaiso();
</script>

</body>
</html>"""

    OUTPUT_PATH.write_text(html_doc, encoding="utf-8")
    print(f"[OK] dashboard 빌드 완료: {OUTPUT_PATH}")
    print(f"     크기: {OUTPUT_PATH.stat().st_size:,} bytes")
    print(f"     섹션: 다이소 Top 30 / 인플루언서 / 핫 컨텐츠 / 우선 섭외")


if __name__ == "__main__":
    build()
