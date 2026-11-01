"""
URL checker for Replit + UptimeRobot.

- Checks every URL once per hour in a background thread.
- GET /          -> HTML report of the latest check
- GET /health    -> 200 "OK" if all HARD urls are fine, 503 otherwise
                    (point an UptimeRobot HTTP or keyword monitor here;
                     the 5-minute ping also keeps the Repl awake)
- GET /check     -> run a check right now
- GET /report.json -> raw results

Install: pip install flask requests
Run:     python main.py
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, Response

CHECK_INTERVAL_SECONDS = 60 * 60  # every hour
TIMEOUT = 20
WORKERS = 4  # keep low so Pixabay doesn't rate-limit you

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ---- URL LIST -------------------------------------------------------------
# SOFT = sites that usually block bots (login walls / anti-bot). A failure here
# is reported as a warning and does NOT make /health fail.
SOFT = [
    "https://www.instagram.com/mohamed_hassan515/",
    "https://www.linkedin.com/in/mohamed-hassan-98647a181",
    "https://www.facebook.com/profile.php?id=100005199706910",
    "https://x.com/Mohassanart",
    "https://youtube.com/@illustrations2",
    "https://pin.it/1V3sRvmU3",
    "https://pxhere.com/en/photographer/767067?order=popular",
    "https://buymeacoffee.com/mohassan",
]

HARD = [
    "https://freeimagesandillustrations.blogspot.com/",
    "https://freeimagesandillustrations.blogspot.com/p/support-us_12.html",
    "https://askarabinfo.blogspot.com/",
    "https://healthandfitness390.blogspot.com",
    "https://theindustrialedge.blogspot.com",
    "https://internationaltravel2.blogspot.com",
    "https://quranweb24hours.blogspot.com/p/blog-page.html",
    "https://quranweb24hours.blogspot.com",
    "https://quranweb24hours.blogspot.com/p/blog-page_23.html",
    "https://freeonlinetools24hours.blogspot.com",
]

PIXABAY_USER = "mohamed_hassan-5229782"
PIXABAY_SOFT = [  # Pixabay often answers bots with 403 (Cloudflare), so soft
    f"https://pixabay.com/users/{PIXABAY_USER}/?tab=latest&pagi={n}"
    for n in range(2, 96)
]
for lang in ["de", "fr", "it", "es", "ru", "nl", "zh", "en", "ja", "ko", "tr",
             "ro", "pt", "hu", "fi", "id", "da", "cs", "sk", "vi"]:
    PIXABAY_SOFT.append(f"https://pixabay.com/{lang}/users/{PIXABAY_USER}/")
SOFT += PIXABAY_SOFT

GOOGLE_TERMS = [
    "illustrations", "pixabay+business", "pixabay+idea", "pixabay+cartoon",
    "pixabay+flower", "pixabay+sport", "pixabay+medical", "pixabay+man",
    "pixabay+woman", "pixabay+silhouette", "pixabay+background",
    "pixabay+finance", "pixabay+socialmedia", "pixabay+seo", "pixabay+icon",
    "pixabay+design", "pixabay+content", "pixabay+physiology", "pixabay+islam",
    "pixabay+Ramadan", "pixabay+gym", "pixabay+people", "pixabay+learning",
    "pixabay+books", "pixabay+education", "pixabay+technology",
]
# Google search pages block bots; they are only checked for a normal response.
SOFT += [f"https://www.google.com/search?q=mohamed_hassan+{t}" for t in GOOGLE_TERMS]

# De-duplicate while keeping order
ALL = []
seen = set()
for u in HARD + SOFT:
    if u not in seen:
        seen.add(u)
        ALL.append((u, u in HARD))
# ---------------------------------------------------------------------------

state = {"checked_at": None, "results": [], "running": False}
lock = threading.Lock()


def check_one(item):
    url, hard = item
    start = time.time()
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        ms = int((time.time() - start) * 1000)
        ok = r.status_code < 400
        note = ""
        if r.url.rstrip("/") != url.rstrip("/"):
            note = f"redirected to {r.url}"
        return dict(url=url, hard=hard, status=r.status_code, ok=ok, ms=ms, note=note)
    except requests.RequestException as e:
        ms = int((time.time() - start) * 1000)
        return dict(url=url, hard=hard, status=None, ok=False, ms=ms,
                    note=type(e).__name__)


def run_check():
    with lock:
        if state["running"]:
            return
        state["running"] = True
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = list(pool.map(check_one, ALL))
        with lock:
            state["results"] = results
            state["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    finally:
        with lock:
            state["running"] = False


def loop():
    while True:
        run_check()
        time.sleep(CHECK_INTERVAL_SECONDS)


app = Flask(__name__)


def summary():
    res = state["results"]
    hard_bad = [r for r in res if r["hard"] and not r["ok"]]
    soft_bad = [r for r in res if not r["hard"] and not r["ok"]]
    return res, hard_bad, soft_bad


@app.route("/")
def index():
    res, hard_bad, soft_bad = summary()
    rows = []
    for r in sorted(res, key=lambda x: (x["ok"], not x["hard"])):
        color = "#2e7d32" if r["ok"] else ("#c62828" if r["hard"] else "#ef6c00")
        rows.append(
            f"<tr><td style='color:{color}'>{'OK' if r['ok'] else ('DOWN' if r['hard'] else 'WARN')}</td>"
            f"<td>{r['status'] or '-'}</td><td>{r['ms']} ms</td>"
            f"<td><a href='{r['url']}'>{r['url']}</a></td><td>{r['note']}</td></tr>"
        )
    html = f"""<html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>URL check</title>
<style>body{{font-family:sans-serif;padding:12px}}td,th{{padding:4px 8px;border-bottom:1px solid #ddd;font-size:13px;word-break:break-all}}</style></head><body>
<h2>URL check</h2>
<p>Last check (UTC): {state['checked_at'] or 'running first check...'}<br>
Total: {len(res)} | Hard failures: {len(hard_bad)} | Warnings: {len(soft_bad)}</p>
<p><a href='/check'>Run now</a> | <a href='/report.json'>JSON</a></p>
<table><tr><th>State</th><th>HTTP</th><th>Time</th><th>URL</th><th>Note</th></tr>{''.join(rows)}</table>
</body></html>"""
    return Response(html, mimetype="text/html")


@app.route("/health")
def health():
    if not state["results"]:
        return Response("OK (first check pending)", status=200)
    _, hard_bad, _ = summary()
    if hard_bad:
        return Response("FAIL: " + ", ".join(r["url"] for r in hard_bad), status=503)
    return Response("OK", status=200)


@app.route("/check")
def check_now():
    run_check()
    return index()


@app.route("/report.json")
def report_json():
    return jsonify(state)


if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
