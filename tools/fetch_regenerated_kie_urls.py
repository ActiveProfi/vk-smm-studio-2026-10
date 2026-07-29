# -*- coding: utf-8 -*-
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in raw and not raw.strip().startswith("#"):
        k, v = raw.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

KEY = os.environ["KIE_API_KEY"]
TASKS = {
    "razbor-post": "093707671621df62c2b8e8de37db859b",
    "law-review-post": "577b8a026cbcb1464930664fcd76fe11",
    "case-post": "1001858d8e40b7ae77f25660c0ed79e7",
    "case-article-cover": "0e46a139df3a068942888e0929fc80c2",
    "expert-post": "80083eb93688911ee0669404c3da406e",
    "expert-article-cover": "ccfe3b3f96818f77750b51b4e7ecc387",
    "calculation-post": "9cd194f4ae59c22e88b36ba2764cff0c",
    "calculation-article-cover": "2854bac57a6a46eb11920a6b8d80b63c",
    "serial-post": "d1c036206672b833dacb0fae29e83474",
    "poll-post": "ab92c977751d9b73ac842282b2088caa",
    "checklist-post": "2adefb87ce6ed108011dd3538f8fc20c",
    "announcement-post": "d7600cf821c51ab32ef5245219736aa2",
}

out = {}
for name, tid in TASKS.items():
    req = urllib.request.Request(
        f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={tid}",
        headers={"Authorization": f"Bearer {KEY}", "Accept": "application/json"},
    )
    data = json.loads(urllib.request.urlopen(req, timeout=60).read())
    rj = data.get("data", {}).get("resultJson", "")
    url = json.loads(rj)["resultUrls"][0] if rj else ""
    out[name] = url
    print(f"{name}\t{url}")

(ROOT / "output" / "rubrics-media-kie-urls.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
)
