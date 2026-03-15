#!/usr/bin/env python3
import json
import re
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
DATA = ROOT / "data" / "flights.json"
WORKER_URL = "https://avi-tlv-refresh-worker.baronclaw.workers.dev/api/refresh"
ALLOWED_ORIGIN = "https://aviclaw.github.io"


def test_1_details_renderer_not_broken_placeholder() -> None:
    html = INDEX.read_text(encoding="utf-8")

    # Regression guard for the exact bug reported by Max
    assert "<tbody>$${''}</tbody>" not in html, "details table still uses broken '$' placeholder"

    # Ensure renderer uses computed body rows
    assert "const body = items.map" in html
    assert "<tbody>${body}</tbody>" in html
    assert "inProgress" in html

    payload = json.loads(DATA.read_text(encoding="utf-8"))
    day = payload["days"]["2026-03-10"]
    arr_examples = day["arrival"]["summary"]["completed_examples"]
    assert len(arr_examples) > 0, "expected arrival examples for details panel"


def test_2_refresh_endpoint_cors_and_post() -> None:
    # CORS preflight must succeed for browser fetch
    opt = subprocess.run(
        [
            "curl",
            "-i",
            "-sS",
            "-X",
            "OPTIONS",
            WORKER_URL,
            "-H",
            f"Origin: {ALLOWED_ORIGIN}",
            "-H",
            "Access-Control-Request-Method: POST",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    out = opt.stdout
    assert "HTTP/2 204" in out or "HTTP/1.1 204" in out
    assert f"access-control-allow-origin: {ALLOWED_ORIGIN}" in out.lower()
    assert "access-control-allow-methods: post, options" in out.lower()

    # Actual POST should be reachable; can be 200 or 429 depending on anti-abuse lock
    post = subprocess.run(
        [
            "curl",
            "-i",
            "-sS",
            "-X",
            "POST",
            WORKER_URL,
            "-H",
            f"Origin: {ALLOWED_ORIGIN}",
            "-H",
            "Content-Type: application/json",
            "--data",
            '{"from":"test-suite"}',
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    pout = post.stdout
    assert (
        "HTTP/2 200" in pout
        or "HTTP/1.1 200" in pout
        or "HTTP/2 429" in pout
        or "HTTP/1.1 429" in pout
    ), "unexpected POST status"
    assert f"access-control-allow-origin: {ALLOWED_ORIGIN}" in pout.lower()
    assert '"ok":true' in pout.lower() or '"error":' in pout.lower()


def test_3_language_toggle_present_and_labels_available() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="langToggleBtn"' in html
    assert "const I18N" in html
    assert "English (USA)" in html
    assert "עברית" in html
    assert "applyLang()" in html


def test_4_search_filter_present_and_enter_triggered() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="flightSearch"' in html
    assert 'id="searchBtn"' in html
    assert 'function runSearch()' in html
    assert "if (e.key === 'Enter')" in html


def test_5_search_sanitization_guards_injection_and_boundary() -> None:
    html = INDEX.read_text(encoding="utf-8")

    # Sanitization + boundary guard exists
    assert ".slice(0, 80)" in html
    assert "replace(/[<>`\"'\\\\;(){}]/g, ' ')" in html
    assert "function escapeHtml" in html

    # Explicitly ensure we do not eval user input
    forbidden = ["eval(", "new Function(", "innerHTML = q", "document.write("]
    for token in forbidden:
      assert token not in html


def test_6_search_handles_not_found_flow() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "NOT FOUND" in html
    assert "No flight or airline matched" in html


def test_7_status_label_maps_active_to_in_progress_for_display() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "const humanStatus" in html
    assert "if (v === 'active') return 'in progress';" in html
    assert "${humanStatus(it.status)}" in html


def test_8_footer_documents_data_source_and_flightradar_usage() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "Aviation Edge API" in html
    assert "https://aviation-edge.com/" in html
    assert "aggregates flight schedule/status data" in html
    assert "Flightradar24" in html
    assert "https://www.flightradar24.com/" in html


def test_9_favicon_is_declared_and_present() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert 'rel="icon"' in html
    assert "favicon.svg" in html
    favicon = ROOT / "favicon.svg"
    assert favicon.exists()
    svg = favicon.read_text(encoding="utf-8")
    assert 'width="16"' in svg and 'height="16"' in svg


def test_10_refresh_job_tracks_new_tlv_day_automatically() -> None:
    workflow = (ROOT / ".github" / "workflows" / "refresh-data.yml").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "fetch_flights.py").read_text(encoding="utf-8")

    assert "LOOKBACK_DAYS: 7" in workflow
    assert "AIRPORT_TZ: Asia/Jerusalem" in workflow
    assert 'LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "7"))' in script
    assert 'AIRPORT_TZ = os.getenv("AIRPORT_TZ", "Asia/Jerusalem")' in script
    assert "datetime.now(ZoneInfo(AIRPORT_TZ)).date()" in script


def test_no_credential_like_strings_in_tracked_text_files() -> None:
    suspicious_patterns = [
        re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
        re.compile(r"ghp_[A-Za-z0-9]{20,}"),
        re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    ]

    allowlist_paths = {
        ".env.example",  # placeholders allowed
    }

    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(ROOT))
        if rel.startswith(".git/") or rel.startswith(".wrangler/"):
            continue
        if rel in allowlist_paths:
            continue

        # best-effort text-only scan
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue

        for pat in suspicious_patterns:
            m = pat.search(content)
            assert not m, f"possible credential pattern found in {rel}"


if __name__ == "__main__":
    test_1_details_renderer_not_broken_placeholder()
    test_2_refresh_endpoint_cors_and_post()
    test_no_credential_like_strings_in_tracked_text_files()
    print("all tests passed")
