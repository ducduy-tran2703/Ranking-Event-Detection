"""Chuẩn hoá thực thể NER của lớp Gold và tính độ nổi bật của từng thực thể trong một bài.

NER của Gold chạy trên CẢ BÀI (tiêu đề + sapo + nội dung), còn mô hình embedding chỉ đọc tiêu đề + sapo.
Vì vậy mỗi thực thể được gắn **vùng** theo offset, và trọng số phụ thuộc vào vùng + số lần nhắc:
một tên chỉ nhắc một lần ở cuối bài gần như không đóng góp vào nhãn yếu.

Offset tính trên văn bản ghép (xem docs/tong-hop.md mục 5.4–5.5):
    "Tiêu đề: {title}\\n\\nSapo: {sapo}\\n\\nNội dung:\\n{content}"
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

TITLE_PREFIX = "Tiêu đề: "
SAPO_PREFIX = "\n\nSapo: "
CONTENT_PREFIX = "\n\nNội dung:\n"
LEAD_CHARS = 800                 # "đoạn đầu" của nội dung

# Trọng số theo vùng xuất hiện tốt nhất của thực thể trong bài
ZONE_WEIGHT = {"title": 3.0, "sapo": 2.0, "lead": 1.2, "body": 0.6}
SINGLE_TOKEN_PER_FACTOR = 0.2    # "Tuấn", "Phương": thường là người khác nhau ở các bài khác nhau

_STRIP_KEY = re.compile(r"[\s.\-–—_/,'’\"“”()\[\]:;!?·]+")
_EDGE_PUNCT = " \t\"'“”‘’.,;:!?()[]{}-–—…·"
_HAS_LETTER = re.compile(r"[^\W\d_]")
_ADMIN_PREFIX = re.compile(
    r"^(tỉnh|thành phố|tp\.?|quận|huyện|thị xã|xã|phường|thị trấn|thủ đô|đặc khu)\s+", re.IGNORECASE)
# Cấp hành chính nằm GIỮA tên cơ quan: "Sở Y tế tỉnh Gia Lai" = "Sở Y tế Gia Lai"
_INNER_ADMIN = re.compile(r"\s+(?:tỉnh|thành phố|tp\.?)\s+(?=\S)", re.IGNORECASE)
# Một âm tiết tiếng Việt (sau khi bỏ dấu): phụ âm đầu? + nguyên âm + phụ âm cuối?
_VI_SYLLABLE = re.compile(r"^(ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|[bcdghklmnprstvx])?[aeiouy]{1,3}"
                          r"(ch|ng|nh|[cmnpt])?$")
_DOC_REF = re.compile(
    r"(nghị quyết|nghị định|thông tư|quyết định|chỉ thị|công văn|kết luận)\s*(?:số\s*)?"
    r"(\d+)", re.IGNORECASE)
# Từ chung đứng một mình — không phải tên riêng
GENERIC = {
    "công an", "bộ", "sở", "ủy", "uỷ", "ương", "tỉnh", "xã", "phường", "huyện", "đoàn", "hội", "dân",
    "đạo", "lịch", "ubnd", "hđnd", "chính quyền", "nhà nước", "bệnh viện", "trường", "luật",
    "nghị định", "nghị quyết", "thông tư", "quân đội", "ngân hàng", "đội", "công ty", "tập đoàn",
    "trung ương", "đảng", "ban", "cục", "viện", "quốc gia", "thành phố", "tp",
}
# Tên chính tờ báo — bỏ khỏi thực thể của bài do chính báo đó đăng
SELF_NAMES = {
    "tuoitre": {"tuổitrẻ", "báotuổitrẻ", "tuổitrẻonline"},
    "thanhnien": {"thanhniên", "báothanhniên"},
    "vnexpress": {"vnexpress"},
    "vietnamnet": {"vietnamnet", "báovietnamnet"},
    "nhandan": {"nhândân", "báonhândân"},
    "baochinhphu": {"báochínhphủ", "báođiệntửchínhphủ", "cổngthôngtinđiệntửchínhphủ"},
}


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _is_vi_syllable(token: str) -> bool:
    """"quan", "thành", "khu" → True; "adidas", "vivo", "9to5mac" → False."""
    base = "".join(c for c in unicodedata.normalize("NFD", token.lower().replace("đ", "d"))
                   if not unicodedata.combining(c))
    return bool(_VI_SYLLABLE.match(base))


def entity_key(text: str) -> str:
    """Khoá gộp tự động: NFC, chữ thường, bỏ dấu chấm / gạch nối / khoảng trắng."""
    return _STRIP_KEY.sub("", nfc(text).lower())


def load_aliases(path: str | Path = "configs/entity_aliases.yaml") -> dict[str, str]:
    import yaml

    with open(path, encoding="utf-8") as f:
        raw = (yaml.safe_load(f) or {}).get("aliases") or {}
    return {entity_key(str(k)): entity_key(str(v)) for k, v in raw.items()}


class EntityNormalizer:
    """`norm(text, label)` → khoá chuẩn (`text_norm`) hoặc None nếu là rác / từ chung."""

    def __init__(self, aliases: dict[str, str]):
        self.aliases = aliases
        self._cache: dict[tuple[str, str], str | None] = {}

    def norm(self, text: str, label: str) -> str | None:
        k = (text, label)
        if k not in self._cache:
            self._cache[k] = self._norm(text, label)
        return self._cache[k]

    def _norm(self, text: str, label: str) -> str | None:
        t = nfc(text).strip(_EDGE_PUNCT)
        if not _HAS_LETTER.search(t):
            return None
        if len(t) < 2 and not (label == "LOC" and t.isupper()):    # giữ "Ý", "Á"; bỏ "X", "T"
            return None
        low = t.lower()
        if label != "PER" and low in GENERIC:                      # "Trường" có thể là tên người
            return None
        if label in ("ORG", "LOC") and t.islower() and " " not in t and _is_vi_syllable(t):
            return None                       # mảnh từ bị cắt: "ủy", "ương", "quan"; giữ "adidas"
        if label == "ORG":
            t = _INNER_ADMIN.sub(lambda m: " " if t[m.end():m.end() + 1].isupper() else m.group(0), t)
        if label == "DOC":
            m = _DOC_REF.search(t)
            if m:
                return entity_key(f"{m.group(1)} {m.group(2)}")
        key = entity_key(t)
        if key in self.aliases:
            return self.aliases[key]
        if label == "LOC":
            stripped = _ADMIN_PREFIX.sub("", t)
            if stripped != t and stripped:
                k2 = entity_key(stripped)
                return self.aliases.get(k2, k2)
        return key


@dataclass(frozen=True)
class Zones:
    title: tuple[int, int]
    sapo: tuple[int, int]
    content_start: int

    def zone(self, start: int) -> str:
        if start < self.title[1]:
            return "title"
        if start < self.sapo[1]:
            return "sapo"
        if start < self.content_start + LEAD_CHARS:
            return "lead"
        return "body"


def zone_bounds(title: str, sapo: str) -> Zones:
    t0 = len(TITLE_PREFIX)
    t1 = t0 + len(title)
    s0 = t1 + len(SAPO_PREFIX)
    s1 = s0 + len(sapo)
    return Zones((t0, t1), (s0, s1), s1 + len(CONTENT_PREFIX))


@dataclass
class ArticleEntity:
    key: str
    label: str
    surface: str           # cách viết gặp đầu tiên (để hiển thị)
    mentions: int
    best_zone: str
    in_head: bool          # có trong tiêu đề hoặc sapo
    salience: float


def article_entities(article: dict, normalizer: EntityNormalizer) -> dict[str, ArticleEntity]:
    """Gộp các lần nhắc trong một bài thành {text_norm: ArticleEntity}."""
    zones = zone_bounds(article.get("title") or "", article.get("sapo") or "")
    own = SELF_NAMES.get((article.get("source") or "").lower(), set())
    ents = [(e, normalizer.norm(e["text"], e["label"])) for e in article.get("entities") or []]
    # Nối tên một chữ với tên đầy đủ TRONG CÙNG BÀI: "Nguyễn Văn Tuấn … ông Tuấn" → một người.
    # Chỉ nối khi trong bài có đúng MỘT tên đầy đủ kết thúc bằng chữ đó (hai "… Tuấn" → mơ hồ, không nối).
    by_last: dict[str, set[str]] = {}
    for e, key in ents:
        words = e["text"].split()
        if key and e["label"] == "PER" and len(words) > 1:
            by_last.setdefault(entity_key(words[-1]), set()).add(key)
    resolved: set[str] = set()
    acc: dict[str, dict] = {}
    for e, key in ents:
        if key is None or key in own:
            continue
        if e["label"] == "PER" and len(e["text"].split()) == 1 and len(by_last.get(key, ())) == 1:
            key = next(iter(by_last[key]))
            resolved.add(key)
        z = zones.zone(e["start_char"])
        a = acc.setdefault(key, {"label": e["label"], "surface": e["text"], "n": 0,
                                 "w": 0.0, "zone": z, "single": True})
        a["n"] += 1
        if ZONE_WEIGHT[z] > a["w"]:
            a["w"], a["zone"] = ZONE_WEIGHT[z], z
        if not (e["label"] == "PER" and len(e["text"].split()) == 1) or key in resolved:
            a["single"] = False
    out = {}
    for key, a in acc.items():
        sal = a["w"] * (1.0 + 0.5 * math.log(a["n"]))
        if a["label"] == "PER" and a["single"]:
            sal *= SINGLE_TOKEN_PER_FACTOR
        out[key] = ArticleEntity(key, a["label"], a["surface"], a["n"], a["zone"],
                                 a["zone"] in ("title", "sapo"), sal)
    return out
