"""Download the public-domain / CC0 Hungarian road sign SVGs from Wikimedia Commons into
assets/kresz and write assets/kresz/index.json (code, file, description, licence, source).

    python3 scripts/fetch_kresz_signs.py               # polite: one file every ~8 s, resumes
    python3 scripts/fetch_kresz_signs.py --index-only  # rebuild index.json from the files present
    KRESZ_DELAY=45 KRESZ_MAX_WAIT=1800 python3 scripts/fetch_kresz_signs.py  # very slow, sits out long waits
    KRESZ_CONTACT=you@example.com python3 scripts/fetch_kresz_signs.py      # contact for Wikimedia's UA policy

Wikimedia rate-limits automated downloads, so this is deliberately slow; it resumes
where it stopped when run again."""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Wikimedia's User-Agent policy asks automated clients for contact details; give yours in
# KRESZ_CONTACT (e-mail or URL). It is not stored anywhere in the project.
_CONTACT = os.environ.get("KRESZ_CONTACT", "").strip()
UA = {"User-Agent": "cad-mcp/0.1 (CAD drawing tool; road sign block import"
                    + (f"; {_CONTACT}" if _CONTACT else "") + ") python-urllib"}
DELAY = float(os.environ.get("KRESZ_DELAY", "8"))  # seconds between files
MAX_WAIT = int(os.environ.get("KRESZ_MAX_WAIT", "300"))  # longest Retry-After to sit out
OUT = Path(__file__).resolve().parents[1] / "assets" / "kresz"
CATS = ["Category:SVG road signs in Hungary"]  # with its subcategories (warning, priority, prohibitory, ...)
SKIP_CATS = ("historic",)  # signs no longer in force


class RateLimited(Exception):
    pass


def get(url, binary=False):
    for _ in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                data = r.read()
                return data if binary else json.loads(data)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            wait = int(exc.headers.get("Retry-After", "0") or 0) or 60
            if wait > MAX_WAIT:
                raise RateLimited(f"Wikimedia asks to wait {wait} s") from exc
            print(f"  {exc.code}, waiting {wait}s", flush=True)
            time.sleep(wait)
        except Exception as exc:
            print(f"  {exc}, retry", flush=True)
            time.sleep(15)
    return None


def api(params):
    return get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json"}))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    meta_file = OUT / "_meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.is_file() else None
    if isinstance(meta, dict) and meta.get("cats") == CATS:
        info = meta["files"]
    else:
        def members(cat, kind):
            out, cont = [], {}
            while True:
                d = api({"action": "query", "list": "categorymembers", "cmtitle": cat, "cmtype": kind, "cmlimit": 500,
                         **cont})
                out += [m["title"] for m in d["query"]["categorymembers"]]
                if "continue" not in d:
                    return out
                cont = {"cmcontinue": d["continue"]["cmcontinue"]}

        cats, todo = [], list(CATS)
        while todo:  # the categories and their subcategories, except historic ones
            c = todo.pop(0)
            if c in cats or any(k in c.lower() for k in SKIP_CATS):
                continue
            cats.append(c)
            todo += members(c, "subcat")
            time.sleep(1)
        titles = []
        for cat in cats:
            titles += members(cat, "file")
            time.sleep(1)
        titles = sorted(set(titles))
        info = []
        for i in range(0, len(titles), 20):
            time.sleep(2)
            d = api({"action": "query", "titles": "|".join(titles[i:i + 20]), "prop": "imageinfo",
                     "iiprop": "url|size|extmetadata", "iiextmetadatafilter": "LicenseShortName|ObjectName|ImageDescription"})
            for p in d["query"]["pages"].values():
                ii = (p.get("imageinfo") or [{}])[0]
                md = ii.get("extmetadata", {})
                info.append({"title": p["title"], "url": ii.get("url"), "license": md.get("LicenseShortName", {}).get("value"),
                             "desc": md.get("ImageDescription", {}).get("value", ""), "name": md.get("ObjectName", {}).get("value", "")})
        meta_file.write_text(json.dumps({"cats": CATS, "categories": cats, "files": info}, ensure_ascii=False),
                             encoding="utf-8")
    wanted = [x for x in info if x["license"] in ("Public domain", "CC0") and x["url"]]
    index = []
    stopped = None
    for n, x in enumerate(wanted, 1):
        fname = x["title"].split(":", 1)[1].replace(" ", "_")
        dest = OUT / fname
        if not (dest.is_file() and dest.stat().st_size > 0) and not stopped and "--index-only" not in sys.argv:
            try:
                data = get(x["url"], binary=True)
            except RateLimited as exc:
                stopped = str(exc)
                data = None
            if data:
                dest.write_bytes(data)
                print(f"{n}/{len(wanted)} {fname}", flush=True)
            time.sleep(DELAY)
        if dest.is_file():
            code = re.sub(r"^Hungary_road_sign_|\.svg$", "", fname)
            if re.search(r"Historic|^1[89]\d\d_", code):  # earlier versions of a sign, no longer in force
                continue
            index.append({"code": code, "file": fname, "name": re.sub(r"<[^>]+>", "", x["name"] or "").strip(),
                          "description": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x["desc"] or "")).strip()[:300],
                          "license": x["license"], "source": "https://commons.wikimedia.org/wiki/" + x["title"].replace(" ", "_")})
    (OUT / "index.json").write_text(json.dumps(sorted(index, key=lambda d: d["code"]), ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    print(f"done: {len(index)} of {len(wanted)} signs" + (f" (stopped: {stopped}; run again later)" if stopped else ""),
          flush=True)
    return 0 if not stopped else 1


if __name__ == "__main__":
    sys.exit(main())
