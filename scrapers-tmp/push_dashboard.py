"""
dashboard.html을 GitHub repo로 자동 push (GitHub Pages 라이브)

대상 repo: aaronkyung-a11y/daiso-ig-dashboard
대상 path: v2/dashboard.html
라이브 URL: https://aaronkyung-a11y.github.io/daiso-ig-dashboard/v2/dashboard.html

PAT 위치: ~/.daiso-monitor/github_pat.txt (한 줄)

실행:
    py push_dashboard.py

매일 자동 실행은 run_daily.bat에 자동 포함.
"""

import base64
import json
import sys
import urllib.error
import ssl
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = "aaronkyung-a11y/daiso-ig-dashboard"
TARGET_PATH = "v2/dashboard.html"
BRANCH = "main"
DASHBOARD_FILE = Path(__file__).parent.parent / "dashboard.html"
PAT_FILE = Path.home() / ".daiso-monitor" / "github_pat.txt"
def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl._create_unverified_context()


SSL_CTX = _ssl_ctx()
LIVE_URL = f"https://aaronkyung-a11y.github.io/daiso-ig-dashboard/{TARGET_PATH}"


def _api_request(method: str, path: str, pat: str, body: dict | None = None) -> dict | None:
    url = f"https://api.github.com{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def get_file_sha(pat: str) -> str | None:
    """기존 파일의 SHA (없으면 None — 신규 파일)."""
    data = _api_request("GET", f"/repos/{REPO}/contents/{TARGET_PATH}?ref={BRANCH}", pat)
    return data["sha"] if data else None


def push_file(content_b64: str, sha: str | None, pat: str) -> dict:
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = {
        "message": f"Update dashboard - {today}",
        "content": content_b64,
        "branch": BRANCH,
    }
    if sha:
        body["sha"] = sha
    return _api_request("PUT", f"/repos/{REPO}/contents/{TARGET_PATH}", pat, body)


def main():
    if not PAT_FILE.exists():
        print(f"[ERROR] PAT 파일 없음: {PAT_FILE}")
        print("       설치: README의 'GitHub Pages 자동 push 설정' 섹션 참고")
        sys.exit(1)

    if not DASHBOARD_FILE.exists():
        print(f"[ERROR] dashboard.html 없음: {DASHBOARD_FILE}")
        print("       먼저 build_dashboard.py 실행")
        sys.exit(1)

    pat = PAT_FILE.read_text().strip()
    content = DASHBOARD_FILE.read_bytes()
    content_b64 = base64.b64encode(content).decode("utf-8")
    size_kb = len(content) / 1024

    print(f"=== GitHub Pages push ===")
    print(f"파일: {DASHBOARD_FILE.name} ({size_kb:.1f} KB)")
    print(f"대상: {REPO}/{TARGET_PATH}")
    print(f"브랜치: {BRANCH}")

    try:
        sha = get_file_sha(pat)
        action = "갱신" if sha else "신규 생성"
        print(f"동작: {action}")

        result = push_file(content_b64, sha, pat)
        commit_sha = result.get("commit", {}).get("sha", "?")[:7]
        print(f"\n[OK] push 완료")
        print(f"     커밋: {commit_sha}")
        print(f"     라이브 URL: {LIVE_URL}")
        print(f"     ※ GitHub Pages 캐시 갱신 30~60초 소요")
    except Exception as e:
        print(f"\n[ERROR] push 실패: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
