"""
인플루언서 평가 엔진

입력:
- logs/ig_reel_store.json (IG 누적 reel store, 60일 윈도우)
- logs/yt_YYYY-MM-DD.json (YT 영상 데이터, 오늘 또는 지정)

출력:
- logs/influencers_YYYY-MM-DD.json (인플루언서별 점수와 메타)

점수 산식 v3 (v2 + 최소 도달 임계값 추가):

YouTube Top 영향력:
  Top = 0.35 × 정규화_평균조회수
      + 0.25 × 참여율
      + 0.15 × 정규화_조회수팔로워비율 (View Ratio)
      + 0.15 × 카테고리적합도 (다이소 언급 비율)
      + 0.10 × 정규화_팔로워

Instagram Top 영향력 (IG는 view·팔로워 비공개라 likes 기반):
  Top = 0.50 × 정규화_평균좋아요
      + 0.25 × ER_proxy (참여율 추정)
      + 0.15 × 카테고리적합도
      + 0.10 × 일관성 (컨텐츠 수)

Rising 점수: 14일 데이터 누적 필요 → 누적 부족 시 None
   (활성화 조건: 같은 user의 데이터가 14일 이상 누적돼야 7일 변화율 산출 가능)

retailer_focus (사후 분류):
- 'daiso_focused': 다이소 언급 비율 ≥ 0.5
- 'daiso_occasional': 0 < 비율 < 0.5
- 'beauty_general': 비율 = 0 (그래도 뷰티 키워드로 검색됐으니 뷰티 관련)
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

CUTOFF_DAYS = 30
RISING_MIN_DAYS = 14


# ============================================================
# 데이터 로드
# ============================================================

def load_ig_reels(reel_store_path: Path = None) -> list[dict]:
    p = reel_store_path or (LOGS_DIR / "ig_reel_store.json")
    if not p.exists():
        return []
    items = json.loads(p.read_text(encoding="utf-8"))
    cutoff = (datetime.now() - timedelta(days=CUTOFF_DAYS)).strftime("%Y-%m-%d")
    return [r for r in items if (r.get("date") or "1900-01-01") >= cutoff]


def load_yt_videos(yt_path: Path = None) -> list[dict]:
    """API yt_*.json + Chrome MCP yt_chrome_*.json 두 source 통합 로드.

    동일 videoId는 중복 제거. Chrome MCP source 우선 (channelName 더 정확).
    """
    if yt_path:
        # 명시적 path 지정 시 단일 파일만
        if not yt_path.exists():
            return []
        return json.loads(yt_path.read_text(encoding="utf-8"))

    # 두 source 모두 로드 — 가장 최근 파일
    api_files = sorted(LOGS_DIR.glob("yt_2*.json"), reverse=True)  # yt_2026-... 형식만 (yt_chrome 제외)
    chrome_files = sorted(LOGS_DIR.glob("yt_chrome_*.json"), reverse=True)

    api_videos = []
    if api_files:
        try:
            api_videos = json.loads(api_files[0].read_text(encoding="utf-8"))
        except Exception:
            pass

    chrome_videos = []
    if chrome_files:
        try:
            chrome_videos = json.loads(chrome_files[0].read_text(encoding="utf-8"))
        except Exception:
            pass

    # videoId 중복 제거 — Chrome MCP 우선 (channelName 더 정확)
    by_id = {}
    for v in api_videos:
        vid = v.get("videoId")
        if vid:
            by_id[vid] = v
    for v in chrome_videos:
        vid = v.get("videoId")
        if vid:
            # Chrome MCP 데이터로 덮어씀 (channelName 정확)
            by_id[vid] = v

    return list(by_id.values())


# ============================================================
# 집계
# ============================================================

def aggregate_ig(reels: list[dict]) -> list[dict]:
    user_stats = defaultdict(lambda: {
        "reels": [], "likes_sum": 0, "comments_sum": 0, "daiso_mentions": 0,
    })
    for r in reels:
        user = r.get("user")
        if not user:
            continue
        s = user_stats[user]
        s["reels"].append(r)
        s["likes_sum"] += r.get("likes") or 0
        s["comments_sum"] += r.get("comments") or 0
        if r.get("mentions_daiso"):
            s["daiso_mentions"] += 1

    out = []
    for user, s in user_stats.items():
        n = len(s["reels"])
        if n == 0:
            continue
        out.append({
            "platform": "instagram",
            "id": f"ig:{user}",
            "username": user,
            "profile_url": f"https://www.instagram.com/{user.lstrip('@')}/",
            "content_count_30d": n,
            "avg_likes": round(s["likes_sum"] / n, 1),
            "avg_comments": round(s["comments_sum"] / n, 1),
            "total_engagement": s["likes_sum"] + s["comments_sum"],
            "daiso_mention_count": s["daiso_mentions"],
            "daiso_mention_ratio": round(s["daiso_mentions"] / n, 3),
            "latest_content_date": max(r.get("date", "") for r in s["reels"]),
            "latest_content_url": max(s["reels"], key=lambda x: x.get("date", ""))["url"],
        })
    return out


def aggregate_yt(videos: list[dict]) -> list[dict]:
    ch_stats = defaultdict(lambda: {
        "videos": [], "views_sum": 0, "likes_sum": 0, "comments_sum": 0,
        "daiso_mentions": 0, "subs": None, "name": None,
    })
    for v in videos:
        ch_id = v.get("channelId")
        if not ch_id:
            continue
        s = ch_stats[ch_id]
        s["videos"].append(v)
        s["views_sum"] += v.get("views") or 0
        s["likes_sum"] += v.get("likes") or 0
        s["comments_sum"] += v.get("comments") or 0
        if v.get("mentions_daiso"):
            s["daiso_mentions"] += 1
        if s["subs"] is None:
            s["subs"] = v.get("channelSubscribers")
            s["name"] = v.get("channelName")

    out = []
    for ch_id, s in ch_stats.items():
        n = len(s["videos"])
        if n == 0:
            continue
        avg_views = s["views_sum"] / n
        view_ratio = avg_views / s["subs"] if s["subs"] and s["subs"] > 0 else 0
        engagement_pct = (
            (s["likes_sum"] + s["comments_sum"]) / s["views_sum"] * 100
            if s["views_sum"] > 0 else 0
        )
        out.append({
            "platform": "youtube",
            "id": f"yt:{ch_id}",
            "channel_id": ch_id,
            "channel_name": s["name"],
            "profile_url": f"https://www.youtube.com/channel/{ch_id}",
            "subscribers": s["subs"],
            "content_count_30d": n,
            "avg_views": round(avg_views, 0),
            "avg_likes": round(s["likes_sum"] / n, 1) if s["likes_sum"] else 0,
            "avg_comments": round(s["comments_sum"] / n, 1) if s["comments_sum"] else 0,
            "view_follower_ratio": round(view_ratio, 3),
            "engagement_pct": round(engagement_pct, 2),
            "daiso_mention_count": s["daiso_mentions"],
            "daiso_mention_ratio": round(s["daiso_mentions"] / n, 3),
            "latest_content_date": max(v.get("publishedAt", "") for v in s["videos"]),
            "latest_content_url": max(s["videos"], key=lambda x: x.get("publishedAt", ""))["url"],
        })
    return out


# ============================================================
# 정규화
# ============================================================

def minmax(values: list, key: str) -> dict:
    """{id: normalized 0~1} 매핑."""
    nums = [v[key] for v in values if v.get(key) is not None]
    if not nums:
        return {}
    lo, hi = min(nums), max(nums)
    if hi == lo:
        return {v["id"]: 0.5 for v in values if v.get(key) is not None}
    return {
        v["id"]: round((v[key] - lo) / (hi - lo), 3)
        for v in values if v.get(key) is not None
    }


# ============================================================
# 점수 산식 v2
# ============================================================

def _floor_penalty_yt(avg_views: float) -> float:
    """YT 최소 도달 임계값 — views 적으면 점수 깎음."""
    if avg_views >= 10000:
        return 1.0
    elif avg_views >= 1000:
        return 0.6
    else:
        return 0.3


def _floor_penalty_ig(avg_likes: float) -> float:
    """IG 최소 도달 임계값 — likes 적으면 점수 깎음 (IG는 view 비공개라 likes로 대체)."""
    if avg_likes >= 500:
        return 1.0
    elif avg_likes >= 100:
        return 0.7
    elif avg_likes >= 50:
        return 0.4
    else:
        return 0.2


def calc_yt_top(ch: dict, n_views: dict, n_subs: dict, n_view_ratio: dict) -> float:
    """YouTube Top 영향력 점수 v3 (최소 도달 임계값 추가)."""
    raw = (
        0.35 * n_views.get(ch["id"], 0) +
        0.25 * min(ch.get("engagement_pct", 0) / 10, 1.0) +  # 10%를 max로 normalize
        0.15 * n_view_ratio.get(ch["id"], 0) +
        0.15 * ch.get("daiso_mention_ratio", 0) +
        0.10 * n_subs.get(ch["id"], 0)
    )
    return round(raw * _floor_penalty_yt(ch["avg_views"]), 3)


def calc_ig_top(user: dict, n_likes: dict, n_engagement: dict) -> float:
    """IG Top 영향력 점수 v3 — IG는 view·팔로워 비공개라 likes 기반.

    참고: IG는 reel view 카운트를 의도적으로 숨김 (Chrome MCP 검증 완료).
    play_count/video_view_count 필드 모두 부재. likes를 도달 proxy로 사용.
    """
    er_proxy = user["avg_comments"] / max(user["avg_likes"], 1)
    consistency = min(user["content_count_30d"] / 5, 1.0)
    raw = (
        0.50 * n_likes.get(user["id"], 0) +
        0.25 * min(er_proxy * 10, 1.0) +
        0.15 * user.get("daiso_mention_ratio", 0) +
        0.10 * consistency
    )
    return round(raw * _floor_penalty_ig(user["avg_likes"]), 3)


def classify_retailer(daiso_ratio: float) -> str:
    if daiso_ratio >= 0.5:
        return "daiso_focused"
    elif daiso_ratio > 0:
        return "daiso_occasional"
    else:
        return "beauty_general"


def calc_rising(_inf: dict) -> float | None:
    """Rising 점수 — 14일 누적 후 활성화. 현재는 None."""
    # TODO: 누적 데이터 14일+ 모이면 7일 변화율 계산
    # 예: 평균조회수증가율_7d, 참여율증가_7d, 신규진입_부스트, 팔로워증가율_7d
    return None


# ============================================================
# 메인
# ============================================================

def evaluate(ig_users: list[dict], yt_channels: list[dict]) -> list[dict]:
    # IG 정규화 + 점수
    if ig_users:
        n_likes = minmax(ig_users, "avg_likes")
        n_engagement = minmax(ig_users, "total_engagement")
        for u in ig_users:
            u["top_score"] = calc_ig_top(u, n_likes, n_engagement)
            u["rising_score"] = calc_rising(u)
            u["retailer_focus"] = classify_retailer(u["daiso_mention_ratio"])

    # YT 정규화 + 점수
    if yt_channels:
        n_views = minmax(yt_channels, "avg_views")
        n_subs = minmax(yt_channels, "subscribers")
        n_view_ratio = minmax(yt_channels, "view_follower_ratio")
        for c in yt_channels:
            c["top_score"] = calc_yt_top(c, n_views, n_subs, n_view_ratio)
            c["rising_score"] = calc_rising(c)
            c["retailer_focus"] = classify_retailer(c["daiso_mention_ratio"])

    return sorted(ig_users + yt_channels, key=lambda x: x.get("top_score", 0), reverse=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ig-store", type=str, default=None)
    parser.add_argument("--yt-json", type=str, default=None)
    args = parser.parse_args()

    print("=== 인플루언서 평가 엔진 ===\n")

    ig_path = Path(args.ig_store) if args.ig_store else None
    yt_path = Path(args.yt_json) if args.yt_json else None
    ig_reels = load_ig_reels(ig_path)
    yt_videos = load_yt_videos(yt_path)

    print(f"IG reel 로드: {len(ig_reels)}개 (최근 {CUTOFF_DAYS}일)")
    print(f"YT 영상 로드: {len(yt_videos)}개")

    if not ig_reels and not yt_videos:
        print("\n[ERROR] 데이터 없음. ig_crawler / yt_crawler 먼저 실행.")
        return

    ig_users = aggregate_ig(ig_reels)
    yt_channels = aggregate_yt(yt_videos)
    print(f"\nIG 인플루언서: {len(ig_users)}명")
    print(f"YT 채널: {len(yt_channels)}개")

    ranked = evaluate(ig_users, yt_channels)

    today = datetime.now().strftime("%Y-%m-%d")
    out_path = LOGS_DIR / f"influencers_{today}.json"
    out_path.write_text(json.dumps(ranked, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out_path}")

    # Top 10 미리보기
    print(f"\n--- Top 영향력 Top 10 ---")
    print(f"{'#':<3}{'플랫폼':<10}{'이름':<25}{'점수':<8}{'주요 지표':<35}{'다이소':<8}{'분류'}")
    print('-' * 100)
    for i, inf in enumerate(ranked[:10], 1):
        if inf["platform"] == "instagram":
            name = inf["username"]
            metric = f"likes평균 {inf['avg_likes']:.0f} (n={inf['content_count_30d']})"
        else:
            name = (inf["channel_name"] or "-")[:22]
            subs = inf.get("subscribers")
            metric = f"views평균 {int(inf['avg_views']):,}" + (f" / 구독 {subs:,}" if subs else "")
        score = inf.get("top_score", 0)
        daiso = f"{inf['daiso_mention_count']}/{inf['content_count_30d']}"
        focus = inf.get("retailer_focus", "")
        print(f"{i:<3}{inf['platform']:<10}{name:<25}{score:<8.3f}{metric:<35}{daiso:<8}{focus}")

    # Rising 안내
    rising_active = sum(1 for x in ranked if x.get("rising_score") is not None)
    if rising_active == 0:
        print(f"\n[INFO] Rising 점수: 14일+ 누적 후 활성화 (현재 누적 부족)")


if __name__ == "__main__":
    main()
