"""Probe Tushare document backend API (dev helper)."""
import re
import httpx

client = httpx.Client(timeout=30, follow_redirects=True)
candidates = [
    "https://tushare.pro/document/doc_detail?doc_id=27",
    "https://tushare.pro/document/detail?doc_id=27",
    "https://tushare.pro/document/get_doc?doc_id=27",
    "https://tushare.pro/wctapi/document/detail?doc_id=27",
]
for url in candidates:
    try:
        r = client.get(url)
        print(r.status_code, url, len(r.text), r.headers.get("content-type", "")[:30])
        if "daily" in r.text or "接口" in r.text:
            print(r.text[:400])
    except Exception as exc:
        print("ERR", url, exc)

r = client.get("https://tushare.pro/js/app.9e6e5488.js")
text = r.text
for m in re.finditer(r"/[a-zA-Z0-9_/-]*doc[a-zA-Z0-9_/-]*", text):
    s = m.group(0)
    if len(s) < 60:
        print(s)
