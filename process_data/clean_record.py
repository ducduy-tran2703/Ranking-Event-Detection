"""
Record-level cleaning: silver/*.jsonl -> clean_silver/*.jsonl (+ rejects.jsonl, stats)
- Ham thuan tuy, xac dinh: dung chung cho train va inference.
- KHONG chua dedup (corpus-level, chay rieng sau buoc nay).
- Silver goc khong bi sua.

Chay:
  python clean_record.py --in silver --out clean_silver
"""
import argparse, glob, json, os, re, unicodedata
from collections import Counter
from datetime import datetime

REQUIRED = ["article_id", "url", "source", "category", "title",
            "sapo", "published_at", "content_text"]

# ---- NGUONG: placeholder, PHAI chinh theo phan phoi thuc te (xem stats) ----
MIN_TITLE_CHARS = 10
MIN_CONTENT_CHARS = 200

# ---- Boilerplate pha 1: quy tac theo nguon ----
# De TRONG co chu y. Can mau duoi/dau bai that cua tung nguon de viet regex,
# khong viet theo doan. Moi phan tu: (vi_tri, regex) voi vi_tri in {"head","tail"}.
BOILERPLATE = {
    # "QDND": [("tail", re.compile(r"\s*Nguồn:.*$"))],
    # "DANTRI": [], "NHANDAN": [], "CHINHPHU": [],
}

_DROP = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)
_TO_SPACE = dict.fromkeys(map(ord, "\u2028\u2029\u00a0\u2009\u202f\t\r\n"), " ")
_WS = re.compile(r"\s+")


def norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s)
    s = s.translate(_DROP).translate(_TO_SPACE)
    return _WS.sub(" ", s).strip()


def strip_boilerplate(text, source):
    for pos, rx in BOILERPLATE.get(source, []):
        text = rx.sub("", text, count=1).strip()
    return text


def parse_ts(s):
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else None   # bat buoc co mui gio
    except (TypeError, ValueError):
        return None


def clean_record(rec):
    """Tra ve (record_sach | None, ly_do_loai | None)."""
    for k in REQUIRED:
        if k not in rec or rec[k] is None:
            return None, f"missing:{k}"
    if parse_ts(rec["published_at"]) is None:
        return None, "bad_published_at"

    out = dict(rec)
    for k in ("title", "sapo", "content_text"):
        out[k] = norm(rec[k])
    out["author"] = norm(rec.get("author") or "") or None
    out["content_text"] = strip_boilerplate(out["content_text"], rec["source"])

    if len(out["title"]) < MIN_TITLE_CHARS:
        return None, "title_too_short"
    if len(out["content_text"]) < MIN_CONTENT_CHARS:
        return None, "content_too_short"   # gom ca content rong

    return out, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    stats, seen = Counter(), set()

    with open(os.path.join(a.out, "rejects.jsonl"), "w", encoding="utf-8") as rj:
        for f in sorted(glob.glob(os.path.join(a.inp, "*.jsonl"))):
            with open(f, encoding="utf-8") as fin, \
                 open(os.path.join(a.out, os.path.basename(f)), "w", encoding="utf-8") as fout:
                for line in fin:
                    rec = json.loads(line)
                    stats[("total", rec.get("source"))] += 1
                    if rec.get("article_id") in seen:
                        out, why = None, "dup_article_id"
                    else:
                        out, why = clean_record(rec)
                    if out is None:
                        stats[("reject", why)] += 1
                        rj.write(json.dumps({"article_id": rec.get("article_id"),
                                             "source": rec.get("source"),
                                             "reason": why}, ensure_ascii=False) + "\n")
                        continue
                    seen.add(out["article_id"])
                    stats[("keep", out["source"])] += 1
                    fout.write(json.dumps(out, ensure_ascii=False) + "\n")

    for k, v in sorted(stats.items(), key=str):
        print(k, v)


if __name__ == "__main__":
    main()
