"""
YouTube 크롤러 — 다이소 뷰티 Top 제품 단위 키워드 검색

사용 API: YouTube Data API v3 (무료 일일 quota 10,000 units)
- search.list: 100 units/call (검색)
- videos.list: 1 unit/call
- channels.list: 1 unit/call

예상 quota 사용:
- 30개 키워드 × 100 = 3,000 units (검색)
- + videos/channels metadata = 수백 units
- 총 ~4,000 units → 일일 quota 내 충분

요구사항:
    pip install requests google-api-python-client
    또는 그냥 requests로 직접 호출 (이 코드)

API 키 설정:
    1. https://console.cloud.google.com → 프로젝트 → YouTube Data API v3 활성화
    2. 사용자 인증 정보 → API 키 생성
    3. 키를 ~/.daiso-monitor/youtube_api_key.txt 에 한 줄로 저장

실행:
    py yt_crawler.py                    # 오늘 daiso JSON 기준
    py yt_crawler.py --top 10           # Top N 제품만
    py yt_crawler.py --max-videos 5     # 키워드당 최대 영상 (기본 10)
    py yt_crawler.py --days 30          # 최근 N일 (기본 30)
"""

import argparse
import json
import sys
import urllib.parse
import ssl
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from keyword_utils import generate_search_keyword, mentions_daiso

# ============================================================
# 설정
# ============================================================

BASE_DIR = Path(__file__).parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

API_KEY_PATH = Path.home() / ".daiso-monitor" / "youtube_api_key.txt"
def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl._create_unverified_context()


_SSL_CTX = _ssl_ctx()
API_BASE = "https://www.googleapis.com/youtube/v3"

DEFAULT_TOP_N = 30
DEFAULT_MAX_VIDEOS_PER_KEYWORD = 10
DEFAULT_DAYS = 30


# ============================================================
# API 호출
# ============================================================

def _api_get(endpoint: str, params: dict, api_key: str) -> dict:
    """YouTube API GET 호출 + JSON 파싱."""
    params = {**params, "key": api_key}
    url = f"{API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "daiso-monitor/1.0"})
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search_videos(keyword: str, max_results: int, days: int, api_key: str) -> list[str]:
    """search.list로 키워드 검색 → videoId 리스트."""
    published_after = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = _api_get("search", {
        "q": keyword,
        "part": "snippet",
        "type": "video",
        "order": "relevance",
        "publishedAfter": published_after,
        "regionCode": "KR",
        "relevanceLanguage": "ko",
        "maxResults": min(max_results, 50),
    }, api_key)
    return [item["id"]["videoId"] for item in data.get("items", [])]


def fetch_video_metadata(video_ids: list[str], api_key: str) -> list[dict]:
    """videos.list로 메타데이터 일괄 조회."""
    if not video_ids:
        return []
    # videos.list는 한 번에 50개까지 가능
    out = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        data = _api_get("videos", {
            "id": ",".join(chunk),
            "part": "snippet,statistics,contentDetails",
        }, api_key)
        out.extend(data.get("items", []))
    return out


def fetch_channel_metadata(channel_ids: list[str], api_key: str) -> dict:
    """channels.list — channel_id → metadata 매핑."""
    if not channel_ids:
        return {}
    unique = list(set(channel_ids))
    out = {}
    for i in range(0, len(unique), 50):
        chunk = unique[i:i + 50]
        data = _api_get("channels", {
            "id": ",".join(chunk),
            "part": "snippet,statistics",
        }, api_key)
        for ch in data.get("items", []):
            out[ch["id"]] = ch
    return out


# ============================================================
# 정제
# ============================================================

def parse_duration(iso: str) -> int:
    """ISO 8601 duration (PT4M30S) → 초 단위."""
    import re
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso or '')
    if not m:
        return 0
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + s


def normalize_video(video: dict, channels: dict, keyword: str, rank: int, product_name: str) -> dict:
    """videos.list 응답 → 평탄한 dict."""
    snippet = video.get("snippet", {})
    stats = video.get("statistics", {})
    content = video.get("contentDetails", {})
    channel_id = snippet.get("channelId")
    ch = channels.get(channel_id, {})
    ch_stats = ch.get("statistics", {})
    ch_snippet = ch.get("snippet", {})

    duration_sec = parse_duration(content.get("duration", ""))
    is_short = duration_sec > 0 and duration_sec <= 60

    views = int(stats.get("viewCount", 0))
    likes = int(stats.get("likeCount", 0)) if stats.get("likeCount") else None
    comments = int(stats.get("commentCount", 0)) if stats.get("commentCount") else None

    # YT 참여율: (likes + comments) / views (likes 비공개면 None)
    engagement = None
    if likes is not None and views > 0:
        engagement = round((likes + (comments or 0)) / views * 100, 2)

    title = snippet.get("title", "")
    description = snippet.get("description", "")
    tags = snippet.get("tags", [])[:10]
    # 다이소 언급 (제목/설명/태그 합쳐서) — retailer_focus 사후 분류용
    daiso_text = title + " " + description + " " + " ".join(tags)
    return {
        "videoId": video["id"],
        "url": f"https://www.youtube.com/watch?v={video['id']}",
        "title": title[:200],
        "description": description[:300],
        "publishedAt": snippet.get("publishedAt", "")[:10],
        "channelId": channel_id,
        "channelName": ch_snippet.get("title") or f"채널_{channel_id[:8]}" if channel_id else "",
        "channelSubscribers": int(ch_stats.get("subscriberCount", 0)) if ch_stats.get("subscriberCount") else None,
        "duration_sec": duration_sec,
        "is_short": is_short,
        "views": views,
        "likes": likes,
        "comments": comments,
        "engagement_pct": engagement,
        "tags": tags,
        "mentions_daiso": mentions_daiso(daiso_text),
        # 매칭 메타
        "brand_keyword": keyword,
        "product_rank": rank,
        "product_name": product_name,
    }


# ============================================================
# 메인
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--max-videos", type=int, default=DEFAULT_MAX_VIDEOS_PER_KEYWORD)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--daiso-json", type=str, default=None)
    args = parser.parse_args()

    if not API_KEY_PATH.exists():
        print(f"[ERROR] YouTube API 키 없음: {API_KEY_PATH}")
        print("       README의 'YouTube API 키 설정' 섹션 참고")
        sys.exit(1)

    api_key = API_KEY_PATH.read_text().strip()

    daiso_path = Path(args.daiso_json) if args.daiso_json else (
        LOGS_DIR / f"daiso_{datetime.now():%Y-%m-%d}.json"
    )
    if not daiso_path.exists():
        print(f"[ERROR] Daiso 결과 없음: {daiso_path}")
        sys.exit(1)

    daiso = json.loads(daiso_path.read_text(encoding="utf-8"))
    beauty = [p for p in daiso if p.get("is_beauty", True)][:args.top]

    print(f"\n=== YouTube 크롤러 시작 ===")
    print(f"대상: {len(beauty)}개 뷰티 제품")
    print(f"키워드당 최대 영상: {args.max_videos}")
    print(f"기간: 최근 {args.days}일")
    print(f"예상 API quota: 약 {len(beauty) * 100 + 200} units (일일 한도 10,000)\n")

    all_videos = []
    all_channel_ids = set()

    # 1단계: 키워드별 검색
    for idx, prod in enumerate(beauty, 1):
        kw = generate_search_keyword(prod["제품명"], prod.get("브랜드"))
        print(f"[{idx}/{len(beauty)}] {prod['순위']}위 '{prod['제품명'][:30]}' → '{kw}'")
        try:
            video_ids = search_videos(kw, args.max_videos, args.days, api_key)
            print(f"    영상 {len(video_ids)}개 발견")
        except Exception as e:
            print(f"    [WARN] 검색 실패: {e}")
            continue

        if not video_ids:
            continue

        # 2단계: 영상 메타데이터
        try:
            videos_meta = fetch_video_metadata(video_ids, api_key)
        except Exception as e:
            print(f"    [WARN] 메타 조회 실패: {e}")
            continue

        # 채널 ID 모음 (3단계에서 한 번에 조회)
        for v in videos_meta:
            ch_id = v.get("snippet", {}).get("channelId")
            if ch_id:
                all_channel_ids.add(ch_id)

        # 임시 저장
        for v in videos_meta:
            all_videos.append({"raw": v, "kw": kw, "rank": prod["순위"], "name": prod["제품명"]})

    # 3단계: 채널 메타 일괄 조회
    print(f"\n채널 정보 일괄 조회: {len(all_channel_ids)}개")
    try:
        channels = fetch_channel_metadata(list(all_channel_ids), api_key)
    except Exception as e:
        print(f"[WARN] 채널 조회 실패: {e}")
        channels = {}

    # 정제
    normalized = [
        normalize_video(item["raw"], channels, item["kw"], item["rank"], item["name"])
        for item in all_videos
    ]

    # 저장
    today = datetime.now().strftime("%Y-%m-%d")
    out_path = LOGS_DIR / f"yt_{today}.json"
    out_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\n=== 완료 ===")
    print(f"수집 영상: {len(normalized)}개")
    print(f"고유 채널: {len(channels)}개")
    print(f"저장: {out_path}")

    # 미리보기 (조회수 상위 5)
    if normalized:
        top5 = sorted(normalized, key=lambda x: x["views"], reverse=True)[:5]
        print("\n--- 조회수 Top 5 ---")
        for v in top5:
            views = f"{v['views']:,}"
            ch = v["channelName"][:20]
            title = v["title"][:50]
            short = "Shorts" if v["is_short"] else "Long"
            eng = f"{v['engagement_pct']}%" if v["engagement_pct"] else "—"
            print(f"  {views:>10} views | {short:6} | {eng:>6} eng | @{ch:20} | {title}")


if __name__ == "__main__":
    main()
