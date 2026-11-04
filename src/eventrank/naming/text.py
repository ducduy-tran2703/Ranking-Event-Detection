"""Hàm văn bản thuần cho mô hình đặt tên — chép NGUYÊN từ notebook huấn luyện
(training/finetune_vit5_naming_kaggle.ipynb, ô 6, 8, 10) để đầu vào lúc suy luận GIỐNG HỆT lúc train.

Luồng dựng đầu vào: `dataset.block(e)` (khối văn bản agent gán nhãn đã đọc: tiêu đề có `[báo ngày giờ]`, `(medoid)`,
dòng sapo) → `clean_input` (medoid đứng đầu, bỏ tiêu đề trùng không phân biệt hoa thường, ≤ 12 tiêu đề, ≤ 3 sapo):

    Tiêu đề: <medoid> | <tiêu đề 2> | … . Tóm tắt: <sapo 1> | <sapo 2> | …

Đã kiểm (03/11/2026): `clean_input`, `medoid_title`, `shorten`, `faithful` của module này cho kết quả trùng 100% hàm trong
notebook trên toàn bộ data/naming/v1/{train,dev}.jsonl. Sửa hàm nào ở đây thì phải huấn luyện lại hoặc kiểm lại.

Phần cuối file (`fix_decode`, `faithful_v2`, `shorten_v2`) là HẬU KIỂM của naming/predict.py, viết sau kiểm tra độc lập
03/11/2026 (data/temp/kiem_tra_pipeline/BAO_CAO.md, mục N2, V2): `faithful` so chuỗi con nên loại nhầm ngày khác định dạng
("14/9/2026" ↔ "14.9.2026") và để lọt "Asiad 20" (chuỗi con của "2026"), lặp thực thể ("Man City thua Man City");
`shorten` cắt cứng giữa cụm từ. `faithful`/`shorten` giữ nguyên để chấm dev và mốc "medoid rút gọn" như notebook.
"""
from __future__ import annotations

import re
import unicodedata

MAX_TITLES, MAX_SAPOS, MAX_SYLLABLES = 12, 3, 20

_TITLE = re.compile(r"^\d+\. \[[^\]]*\] (.*?)( \(medoid\))?$")
_SAPO = re.compile(r"^- \(\d+\) (.*)$")
_PUNCT = re.compile(r"[^\w\s]")
_NUM = re.compile(r"\d+(?:[.,/:-]\d+)*")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s).strip()


def parse_block(block: str) -> tuple[list[str], int | None, list[str]]:
    """→ (danh sách tiêu đề theo thời gian, chỉ số medoid hoặc None, danh sách sapo)."""
    titles, medoid, sapos = [], None, []
    for line in block.splitlines():
        m = _TITLE.match(line)
        if m:
            if m.group(2):
                medoid = len(titles)
            titles.append(nfc(m.group(1)))
            continue
        m = _SAPO.match(line)
        if m:
            sapos.append(nfc(m.group(1)))
    return titles, medoid, sapos


def clean_input(block: str, max_titles: int = MAX_TITLES, max_sapos: int = MAX_SAPOS) -> str:
    """Khối văn bản → đầu vào mô hình (bỏ mã sự kiện, tên báo, giờ đăng — mô hình dễ học chép ngày vào tên)."""
    titles, medoid, sapos = parse_block(block)
    order = ([medoid] if medoid is not None else []) + [i for i in range(len(titles)) if i != medoid]
    seen, kept = set(), []
    for i in order:
        key = titles[i].lower()
        if key not in seen:
            seen.add(key)
            kept.append(titles[i])
    text = "Tiêu đề: " + " | ".join(kept[:max_titles]) + " ."
    if sapos:
        text += " Tóm tắt: " + " | ".join(sapos[:max_sapos])
    return text


def medoid_title(block: str) -> str:
    titles, medoid, _ = parse_block(block)
    return titles[medoid if medoid is not None else 0]


def syl(s: str) -> list[str]:
    """Âm tiết để chấm ROUGE: NFC, chữ thường, bỏ dấu câu, tách khoảng trắng."""
    return _PUNCT.sub(" ", unicodedata.normalize("NFC", s).lower()).split()


def faithful(pred: str, src: str) -> bool:
    """Kiểm tra trung thực THÔ: mọi con số và mọi từ viết hoa giữa câu (tên riêng) của `pred` đều có trong `src` (đầu vào
    đã làm sạch). Không NER, không alias; không bắt được sai nghĩa khi mọi từ đều có trong cụm (xem README mô hình)."""
    low = unicodedata.normalize("NFC", src).lower()
    nums_ok = all(n in src for n in _NUM.findall(pred))
    words = pred.split()[1:]                                     # bỏ chữ đầu câu (luôn viết hoa)
    caps = [w.strip(",.;:!?()\"'“”") for w in words if w[:1].isupper()]
    return nums_ok and all(w.lower() in low for w in caps if w)


def shorten(title: str, k: int = MAX_SYLLABLES) -> str:
    """Medoid rút gọn theo luật: bỏ tiền tố ngắn trước dấu hai chấm ("Video:", "Hà Nội:"; tiền tố dài → thay ':' bằng
    ','), bỏ ngoặc kép và dấu hỏi, cắt còn ≤ k âm tiết."""
    t = title
    if ":" in t:
        left, right = t.split(":", 1)
        t = right if len(left.split()) <= 3 else left + "," + right
    t = re.sub(r"[\"'“”‘’?]", "", t).strip(" .,-")
    w = t.split()
    return " ".join(w[:k]).rstrip(",;-") if len(w) > k else t


# ---- Hậu kiểm của predict (không dùng lúc train/chấm dev) ----

_U_SPLIT = re.compile(r"\b([UV])(\d) (\d)\b")                     # "U2 3" → "U23" (lỗi giải mã của ViT5)
_U_SPACE = re.compile(r"\bU (\d{2})\b")                            # "U 20" → "U20"
_SPACE_PUNCT = re.compile(r"\s+([,.;:!?])")                         # "Hà Nội , ..." → "Hà Nội, ..."
_NUM_TOK = re.compile(r"(?<!\w)\d+(?:[.,/:-]\d+)*")                 # số không dính chữ bên trái (bỏ m2, U23)
_NUM_SEP = re.compile(r"[./:-]")
_STRIP = ",.;:!?()\"'“”‘’"
# Từ được phép đứng giữa hai lần lặp một thực thể mà vẫn coi là lặp vô nghĩa ("A thua A", "A và A", "A, A").
_REL = {"thua", "thắng", "gặp", "hòa", "hoà", "hạ", "vs", "đấu", "và", "với", "ông", "bà", "vốn", "-", "–"}
# Viết tắt hay gặp ↔ dạng đầy đủ (chữ thường). Viết tắt bằng chữ cái đầu (MTTQ, UBND…) còn được nhận qua `_acronym_ok`.
ALIASES = {
    "tp.hcm": ["thành phố hồ chí minh", "tp hồ chí minh", "tphcm", "tp hcm", "hcm"],
    "tphcm": ["thành phố hồ chí minh", "tp hồ chí minh", "tp.hcm", "tp hcm", "hcm"],
    "hlv": ["huấn luyện viên"], "vđv": ["vận động viên"], "clb": ["câu lạc bộ"],
    "hcv": ["huy chương vàng"], "hcb": ["huy chương bạc"], "hcđ": ["huy chương đồng"],
    "gd-đt": ["giáo dục và đào tạo", "gd&đt", "gdđt"], "gd&đt": ["giáo dục và đào tạo", "gd-đt", "gdđt"],
    "ubnd": ["ủy ban nhân dân", "uỷ ban nhân dân"], "mttq": ["mặt trận tổ quốc"],
    "đh": ["đại học"], "đhqg": ["đại học quốc gia"], "thpt": ["trung học phổ thông"], "thcs": ["trung học cơ sở"],
}


def fix_decode(s: str) -> str:
    """Sửa lỗi giải mã hay gặp trong tên mô hình: "U2 3" → "U23", "U 20" → "U20", " ," → ",". """
    return _SPACE_PUNCT.sub(r"\1", _U_SPACE.sub(r"U\1", _U_SPLIT.sub(r"\1\2\3", s)))


def _num_parts(n: str) -> tuple[str, ...]:
    """'14.9.2026' / '14-09-2026' / '14/9/2026' → ('14', '9', '2026'): '. - / :' là cùng một loại phân cách, bỏ số 0
    đầu. Dấu phẩy giữ trong thành phần (số thập phân "3,92")."""
    return tuple(str(int(p)) if p.isdigit() else p for p in _NUM_SEP.split(n) if p)


def _numbers_ok(pred: str, src: str) -> bool:
    """Mọi số của tên phải là dãy con LIÊN TIẾP các thành phần của một số trong nguồn ("16/9" ⊂ "16-9-2026"), so theo
    token số — "20" không khớp "2026"."""
    have = [_num_parts(n) for n in _NUM_TOK.findall(src)]

    def inside(c: tuple[str, ...]) -> bool:
        return any(s[i:i + len(c)] == c for s in have for i in range(len(s) - len(c) + 1))
    return all(inside(_num_parts(n)) for n in _NUM_TOK.findall(pred))


def _tokens(s: str) -> list[str]:
    return _PUNCT.sub(" ", unicodedata.normalize("NFC", s).lower()).split()


def _acronym_ok(word: str, toks: list[str]) -> bool:
    """Từ viết tắt toàn chữ hoa (2–6 chữ) = chữ cái đầu của một dãy token liên tiếp trong nguồn (bỏ "và")."""
    w = re.sub(r"[^\w]", "", word).lower()
    if not (2 <= len(w) <= 6 and word.upper() == word and w.isalpha()):
        return False
    init = "".join(t[0] for t in toks if t != "và")
    return w in init


def _caps_ok(pred: str, src: str) -> bool:
    """Mọi từ viết hoa giữa câu khớp THEO TOKEN (không phân biệt hoa thường; token của tên là tiền tố của một token
    nguồn — "KOL" ↔ "KOLs"), hoặc là viết tắt có trong ALIASES / chữ cái đầu của một cụm trong nguồn."""
    low_src = unicodedata.normalize("NFC", src).lower()
    toks = _tokens(src)
    for k, als in ALIASES.items():                                   # nguồn viết tắt, tên viết đầy đủ
        if k in low_src:
            toks += [t for a in als for t in _tokens(a)]
    for w in pred.split()[1:]:
        w = w.strip(_STRIP)
        if not w[:1].isupper():
            continue
        alias = ALIASES.get(w.lower())
        if alias and any(a in low_src for a in alias):
            continue
        parts = _tokens(w)
        if parts and all(any(t.startswith(p) for t in toks) for p in parts):
            continue
        if _acronym_ok(w, toks):
            continue
        return False
    return True


def _repeated(pred: str) -> list[str]:
    """Cụm viết hoa xuất hiện 2 lần mà giữa hai lần chỉ có từ quan hệ/hư từ (`_REL`) hoặc dấu phẩy."""
    raw = pred.split()
    toks = [w.strip(_STRIP) for w in raw]
    spans, i = [], 0
    while i < len(toks):
        if toks[i][:1].isupper():
            j = i
            while j < len(toks) and toks[j][:1].isupper():
                j += 1
                if raw[j - 1].endswith((",", ";")):
                    break
            spans.append((" ".join(toks[i:j]).lower(), i, j))
            i = j
        else:
            i += 1
    return [a[0] for k, a in enumerate(spans) for b in spans[k + 1:]
            if a[0] == b[0] and all(t.lower() in _REL for t in toks[a[2]:b[1]] if t)]


def faithful_v2_reasons(pred: str, src: str) -> list[str]:
    """Lý do tên `pred` không đạt so với đầu vào `src` (rỗng = đạt): `so` (số không có trong nguồn), `ten_rieng` (từ viết
    hoa không có), `lap_thuc_the`. Vẫn là phép kiểm THÔ: không bắt được sai nghĩa khi mọi từ đều có trong cụm."""
    pred = fix_decode(pred)
    out = []
    if not _numbers_ok(pred, src):
        out.append("so")
    if not _caps_ok(pred, src):
        out.append("ten_rieng")
    if _repeated(pred):
        out.append("lap_thuc_the")
    return out


def faithful_v2(pred: str, src: str) -> bool:
    return not faithful_v2_reasons(pred, src)


# Ranh giới được cắt: TRƯỚC các liên từ / giới từ mở mệnh đề phụ (trừ khi từ trước cũng thuộc nhóm này: "đối với",
# "sau khi"), hoặc SAU từ kết thúc bằng dấu câu.
_BREAK = {"và", "nhưng", "khi", "để", "vì", "do", "sau", "trước", "trong", "tại", "với", "cho", "từ", "đến", "tới",
          "theo", "về", "nhằm", "đối", "bằng", "giữa", "trên", "dưới", "song", "mà", "thì", "nên", "nếu", "dù", "của",
          "khiến", "làm"}


def shorten_v2(title: str, k: int = 22, min_words: int = 6) -> str:
    """Như `shorten` nhưng không cắt giữa cụm từ: khi dài hơn k âm tiết, cắt ở ranh giới gần k nhất mà vẫn giữ
    ≥ max(min_words, k/2) từ — ưu tiên sau dấu câu, không có thì trước liên từ/giới từ; không có ranh giới nào thì cắt
    cứng ở k rồi bỏ hư từ cuối."""
    t = title
    if ":" in t:
        left, right = t.split(":", 1)
        t = right if len(left.split()) <= 3 else left + "," + right
    t = re.sub(r"[\"'“”‘’?]", "", t).strip(" .,-")
    w = t.split()
    if len(w) <= k:
        return t
    lo = max(min_words, k // 2)
    punct = [j for j in range(lo, k + 1) if w[j - 1][-1] in ",;:.!–-)"]
    conj = [j for j in range(lo, k + 1)
            if w[j].lower() in _BREAK and w[j - 1].lower().strip(_STRIP) not in _BREAK]
    cuts = punct or conj
    if cuts:
        out = w[:max(cuts)]
    else:
        out = w[:k]
        while len(out) > lo and out[-1].lower().strip(_STRIP) in _BREAK:
            out.pop()
    return " ".join(out).rstrip(",;:-–")
