"""
평가 큐 자동 push — Google Form 자동 제출 (기존 시스템과 동일 큐)

Form URL: https://forms.gle/AJy44jhXyYrS3D7S8
- 화면 큐(8 대기 / N 완료)에 자동 누적
- 평일 09/14/17 자동 평가 task가 처리

흐름:
1. 우리 latest influencers JSON 로드
2. 기존 _index.json fetch (이미 평가 완료된 사람)
3. 기존 Form 응답 CSV fetch (이미 큐에 있거나 완료된 URL)
4. 미평가 + 큐 미등록 + 도달 임계값 통과 + 우리 Top 점수 상위 N명
5. Google Form POST 자동 제출

실행:
    py push_eval_queue.py
    py push_eval_queue.py --max 14    # 하루 최대 (기본 10)
    py push_eval_queue.py --dry-run   # 후보만 출력
"""

import argparse
import csv
import io
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# Google Form
FORM_RESPONSE_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSdIggse5qND0InQC83gF6KkWO0ZZJMKYw_bPjtOmpjBS2tmAQ/formResponse"
)
FORM_FIELD_URL = "entry.1373707199"
FORM_RESPONSES_CSV = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vTgag82A2UQN9fDaxWsjTghZSnYoUbflo1e2QM6upF3n3WKvxFCJz8JCDIvnpnxj6yNhgsVJJSHy6rU"
    "/pub?output=csv"
)
EVAL_INDEX_URL = (
    "https://raw.githubusercontent.com/aaronkyung-a11y/daiso-ig-dashboard"
    "/main/influencers/_index.json"
)

LOGS_DIR = Path(__file__).parent.parent / "logs"
DEFAULT_MAX = 10


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl._create_unverified_context()


SSL_CTX = _ssl_ctx()


def _username_from_url(url: str) -> str | None:
    """프로필/계정 URL → username (lowercase, @ stripped)."""
    if not url:
        return None
    u = url.lower().strip()
    if "instagram.com/" in u:
        rest = u.split("instagram.com/")[1].rstrip("/").split("?")[0].split("/")[0]
        return rest or None
    if "youtube.com/" in u:
        rest = u.split("youtube.com/")[1].rstrip("/")
        if rest.startswith("@"):
            return rest[1:]
        if rest.startswith("channel/"):
            return rest.replace("channel/", "").split("/")[0]
        return rest.split("/")[0]
    return None


def fetch_eval_done() -> set[str]:
    """기존 평가 완료된 username 집합."""
    try:
        req = urllib.request.Request(EVAL_INDEX_URL, headers={"User-Agent": "daiso-monitor/1.0"})
        with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {r.get("username", "").lower().lstrip("@") for r in data.get("records", [])}
    except Exception as e:
        print(f"[WARN] _index.json fetch 실패: {e}")
        return set()


def fetch_form_queue() -> set[str]:
    """기존 Form 응답에 등록된 username 집합 (큐 + 완료 모두)."""
    try:
        req = urllib.request.Request(FORM_RESPONSES_CSV, headers={"User-Agent": "daiso-monitor/1.0"})
        with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
            text = resp.read().decode("utf-8")
        usernames = set()
        for row in csv.reader(io.StringIO(text)):
            for cell in row:
                u = _username_from_url(cell.strip())
                if u:
                    usernames.add(u)
        return usernames
    except Exception as e:
        print(f"[WARN] Form CSV fetch 실패: {e}")
        return set()


def submit_to_form(profile_url: str) -> bool:
    """Google Form POST 제출 — 성공 시 True."""
    data = urllib.parse.urlencode({FORM_FIELD_URL: profile_url}).encode("utf-8")
    req = urllib.request.Request(
        FORM_RESPONSE_URL, data=data, method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "daiso-monitor/1.0",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
            return resp.status in (200, 302)
    except urllib.error.HTTPError as e:
        # Google Form은 성공 시 302 또는 200, 그 외 실패
        return e.code in (200, 302)


def load_our_influencers() -> list[dict]:
    files = sorted(LOGS_DIR.glob("influencers_*.json"), reverse=True)
    if not files:
        return []
    return json.loads(files[0].read_text(encoding="utf-8"))


def select_candidates(our_inf, eval_done, queue_existing, max_n):
    candidates = []
    for inf in our_inf:
        # YT는 channel_name이 빌 수 있어서 channel_id fallback (UCxxxxxxxx → 매칭용)
        raw_name = inf.get("username") or inf.get("channel_name") or inf.get("channel_id") or ""
        name = raw_name.lower().lstrip("@")
        profile_url = inf.get("profile_url")
        if not name or not profile_url:
            continue
        if name in eval_done:
            continue
        if name in queue_existing:
            continue
        avg_likes = inf.get("avg_likes") or 0
        avg_views = inf.get("avg_views") or 0
        if avg_likes < 50 and avg_views < 5000:
            continue
        candidates.append(inf)
    candidates.sort(key=lambda x: x.get("top_score", 0), reverse=True)
    return candidates[:max_n]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=DEFAULT_MAX,
                        help=f"하루 최대 제출 (기본 {DEFAULT_MAX})")
    parser.add_argument("--dry-run", action="store_true",
                        help="실제 제출 안 하고 후보만 출력")
    args = parser.parse_args()

    print("=== 평가 큐 자동 push (Google Form 자동 제출) ===")
    our_inf = load_our_influencers()
    if not our_inf:
        print("[ERROR] 우리 인플루언서 데이터 없음 (먼저 influencer_eval.py 실행)")
        sys.exit(1)
    print(f"우리 인플루언서: {len(our_inf)}명")

    eval_done = fetch_eval_done()
    print(f"기존 평가 완료: {len(eval_done)}명")

    queue_existing = fetch_form_queue()
    print(f"기존 Form 큐+완료: {len(queue_existing)}명")

    candidates = select_candidates(our_inf, eval_done, queue_existing, args.max)
    print(f"\n신규 push 대상: {len(candidates)}명")

    if not candidates:
        print("[INFO] 새로 푸시할 인플루언서 없음 (모두 평가/큐 등록됨, 또는 도달 미달)")
        return

    pushed = 0
    for inf in candidates:
        name = inf.get("username") or inf.get("channel_name", "?")
        profile_url = inf.get("profile_url")
        score = inf.get("top_score", 0)

        if args.dry_run:
            print(f"  [DRY] @{name} (점수 {score:.3f}) → {profile_url}")
            continue

        if submit_to_form(profile_url):
            print(f"  [OK] @{name} (점수 {score:.3f}) → Form 제출")
            pushed += 1
        else:
            print(f"  [FAIL] @{name}")

    if not args.dry_run:
        print(f"\n총 {pushed}/{len(candidates)} push 완료")
        print("화면 확인: https://aaronkyung-a11y.github.io/daiso-ig-dashboard/influencer-eval.html")


if __name__ == "__main__":
    main()
