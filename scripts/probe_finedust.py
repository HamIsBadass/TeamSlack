"""Probe fine-dust proxy with different encodings + inputs."""
import urllib.request
import urllib.parse
import urllib.error
import json
import sys

HINTS = ["부산", "제주", "제주시", "강릉", "강릉시", "수원", "광진구", "성남시", "성남 분당구", "분당구", "판교", "연수구"]
BASE = "https://k-skill-proxy.nomadamas.org/v1/fine-dust/report"


def probe(hint: str, encoding: str = "utf-8") -> None:
    enc = urllib.parse.quote(hint.encode(encoding))
    url = f"{BASE}?regionHint={enc}"
    req = urllib.request.Request(url, headers={"User-Agent": "teamslack/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
            print(f"  [{encoding}] OK:", json.dumps(data, ensure_ascii=False)[:400])
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  [{encoding}] HTTP {e.code}: {body[:300]}")
    except Exception as e:
        print(f"  [{encoding}] {type(e).__name__}: {e}")


for hint in HINTS:
    print(f"\n--- {hint} ---")
    probe(hint, "utf-8")
