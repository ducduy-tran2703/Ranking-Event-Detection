"""Local BamiBERT NER inference and guideline-based post-processing."""
from __future__ import annotations

import json
import re
import threading
from bisect import bisect_left, bisect_right
from pathlib import Path

from eventrank.rag.text import validate_entities

LABELS = ("PER", "ORG", "LOC", "EVENT", "DOC", "PRODUCT")
BIO_LABELS = ["O"] + [f"{prefix}-{label}" for label in LABELS for prefix in ("B", "I")]
UNIT_RE = re.compile(r"\w+|[^\w\s]")

_NAME_PARTICLES = frozenset({
    "bin", "ibn", "bint", "al", "el", "de", "del", "della", "di", "da", "das", "dos", "du",
    "van", "von", "der", "den", "le", "la", "ter", "zu", "y", "mac",
})
_TITLE_PREFIX_RE = re.compile(
    r"^(Phó Tổng thống|Tổng thống|Thủ tướng|Tổng Bí thư|Chủ tịch nước|Chủ tịch|Ngoại trưởng|"
    r"Bộ trưởng|Nữ hoàng|Quốc vương|Hoàng hậu|Hoàng tử|Hoàng thân|Thái tử|Công chúa|Giáo hoàng|"
    r"Vua|Phó vương)\s+(?=\S)"
)
_PURE_TITLES = frozenset({
    "thủ tướng", "thủ tướng chính phủ", "phó thủ tướng", "phó thủ tướng thường trực",
    "chủ tịch", "chủ tịch nước", "chủ tịch quốc hội", "phó chủ tịch", "phó chủ tịch nước",
    "phó chủ tịch quốc hội", "chủ tịch ubnd", "chủ tịch hđnd", "phó chủ tịch ubnd",
    "phó chủ tịch hđnd", "tổng bí thư", "tổng bí thư, chủ tịch nước", "bí thư", "phó bí thư",
    "bí thư tỉnh ủy", "bí thư thành ủy", "bộ trưởng", "thứ trưởng", "viện trưởng",
    "phó viện trưởng", "giám đốc", "phó giám đốc", "tổng giám đốc", "cục trưởng",
    "chi cục trưởng", "trưởng ban", "phó trưởng ban", "đại biểu", "đại biểu quốc hội",
    "chủ nhiệm", "phó chủ nhiệm", "chủ nhiệm văn phòng chủ tịch nước", "hlv", "hlv trưởng",
    "huấn luyện viên", "huấn luyện viên trưởng", "trọng tài", "đại tướng", "thượng tướng",
    "trung tướng", "thiếu tướng", "đại tá", "thượng tá", "trung tá", "thiếu tá",
    "bác sĩ", "luật sư", "cán bộ", "công chức", "nghệ sĩ", "ca sĩ", "diễn viên",
    "tổng", "tổng thống", "phó tổng thống", "ngoại trưởng", "nữ hoàng", "quốc vương",
    "hoàng hậu", "hoàng tử", "thái tử", "công chúa", "giáo hoàng", "vua",
})
_GENERIC_ALONE = frozenset({
    "đội tuyển", "tuyển quốc gia", "đội tuyển quốc gia", "đội", "tuyển", "thành phố", "tỉnh",
    "nước", "nhà nước", "đảng", "trung ương", "ubnd", "hđnd", "sở", "bộ", "chính quyền",
    "địa phương", "khu vực", "vùng cao", "hè", "thí sinh", "học sinh", "sinh viên", "cán bộ",
    "công chức", "viên chức", "sĩ quan", "cựu chiến binh", "chó", "mèo", "bão",
    "áp thấp nhiệt đới", "lễ tốt nghiệp", "lễ khai mạc", "lễ bế mạc", "hội thảo", "cuộc họp",
    "phiên họp", "hội nghị", "thông tư", "nghị định", "nghị quyết", "luật", "quyết định",
    "kế hoạch", "đề án", "chỉ thị", "tiêu đề", "sapo", "nội dung", "tổng bí thư, chủ tịch nước",
    "tổng bí thư", "chủ tịch nước", "thủ tướng", "thủ tướng chính phủ", "chủ tịch quốc hội",
    "phó thủ tướng", "bộ trưởng", "clb", "công an", "quân đội", "viện", "tập đoàn",
    "trung tâm", "diễn đàn", "đại hội", "thường trực", "bệnh", "bệnh viện", "ủy ban nhân dân",
})
_CURRENCY_OK = frozenset({"vnd", "usd", "euro"})
_TEMPLATE_LABELS = frozenset({"tiêu đề", "sapo", "nội dung"})
_PER_INITIALS_RE = re.compile(r"^[A-ZĐ]\.?$")
_FORCED_LABELS = {
    "VN-Index": "PRODUCT", "HNX-Index": "PRODUCT", "UPCoM-Index": "PRODUCT", "HNX30": "PRODUCT",
    "VN30": "PRODUCT", "S&P 500": "PRODUCT", "Dow Jones": "PRODUCT", "Nasdaq": "PRODUCT",
    "YouTube": "PRODUCT", "X": "PRODUCT", "Weibo": "PRODUCT", "Truth Social": "PRODUCT",
    "Facebook": "PRODUCT", "TikTok": "PRODUCT", "Zalo": "PRODUCT", "Instagram": "PRODUCT",
    "ChatGPT": "PRODUCT", "VNeID": "PRODUCT", "IELTS": "PRODUCT",
    "USS Abraham Lincoln": "PRODUCT", "The Odyssey": "PRODUCT",
    "Nhà Trắng": "ORG", "Lầu Năm Góc": "ORG", "Điện Kremlin": "ORG", "Zootaxa": "ORG",
}
_FORCED_PATTERNS = [
    (re.compile(r"^Giải thưởng\s"), "EVENT"),
    (re.compile(r"^Quốc hội khóa\s"), "ORG"),
]


def unit_spans(text: str) -> list[tuple[int, int]]:
    """Split text into syllable/punctuation spans matching NER_Detect UNIT_RE."""
    return [(m.start(), m.end()) for m in UNIT_RE.finditer(text)]


def unit_windows(tstart: list[int], tend: list[int], budget: int, overlap: int) -> list[tuple[int, int, int, int]]:
    """Split token spans into overlapping windows <= budget tokens, keeping core [c, d) labels."""
    n = len(tstart)
    wins, a = [], 0
    while True:
        b = max(bisect_right(tend, tstart[a] + budget), a + 1)
        wins.append([a, b])
        if b >= n:
            break
        a = max(bisect_left(tstart, tend[b - 1] - overlap), a + 1)
    out = []
    for k, (wa, wb) in enumerate(wins):
        c = wa if k == 0 else (wins[k - 1][1] + wa) // 2
        d = wb if k == len(wins) - 1 else (wb + wins[k + 1][0]) // 2
        out.append((wa, wb, c, d))
    return out


def spans_from_bio(units: list[tuple[int, int]], tags: list[str], text: str) -> list[dict]:
    """Convert unit-level BIO tags to validated entity dicts."""
    spans, cur = [], None
    for (start, end), tag in zip(units, tags, strict=True):
        if tag.startswith("B-") or (tag.startswith("I-") and (cur is None or cur[2] != tag[2:])):
            if cur:
                spans.append(tuple(cur))
            cur = [start, end, tag[2:]]
        elif tag.startswith("I-"):
            cur[1] = end
        else:
            if cur:
                spans.append(tuple(cur))
            cur = None
    if cur:
        spans.append(tuple(cur))
    return [
        {"text": text[s:e], "label": label, "start_char": s, "end_char": e}
        for s, e, label in spans
    ]


def _forced_label(text: str) -> str | None:
    if text in _FORCED_LABELS:
        return _FORCED_LABELS[text]
    for rx, label in _FORCED_PATTERNS:
        if rx.search(text):
            return label
    return None


def clean_entities(entities: list[dict], text: str) -> list[dict]:
    """Apply clean_silver_ner.py post-processing rules C1..C6 and validate output."""
    cleaned = []
    for e in entities:
        t, lab, low = e["text"], e["label"], e["text"].lower()
        if lab == "PER":
            first = t.split()[0]
            if first[:1].islower() and first.lower() not in _NAME_PARTICLES:
                m = next((m for m in re.finditer(r"\s(\S)", t) if m.group(1).isupper()), None)
                if m is None:
                    continue
                s = e["start_char"] + m.start(1)
                e = {**e, "text": text[s:e["end_char"]], "start_char": s}
                t, low = e["text"], e["text"].lower()
            if _PER_INITIALS_RE.match(t) or low in _PURE_TITLES:
                continue
            m = _TITLE_PREFIX_RE.match(t)
            if m and t[m.end():][:1].isupper():
                s = e["start_char"] + m.end()
                e = {**e, "text": text[s:e["end_char"]], "start_char": s}
                t, low = e["text"], e["text"].lower()

        template_ok = low in _TEMPLATE_LABELS and text[e["end_char"]:e["end_char"] + 1] != ":"
        if (low in _GENERIC_ALONE and lab != "PER" and not template_ok
                and not (lab in ("ORG", "EVENT") and low in _CURRENCY_OK)):
            continue
        if lab == "DOC" and " " not in t and not re.search(r"\d", t) and not t.isupper():
            continue
        forced = _forced_label(t)
        if forced and forced != lab:
            e = {**e, "label": forced}
        cleaned.append(e)
    return validate_entities(text, cleaned)


def encode_texts(tokenizer, texts: list[str], *, max_len: int = 2048, overlap: int = 512):
    """Pre-tokenize texts into unit spans and sliding-window BamiBERT inputs."""
    units_all = [unit_spans(text) for text in texts]
    words_all = [
        [(" " if s > 0 and text[s - 1].isspace() else "") + text[s:e] for s, e in units]
        for text, units in zip(texts, units_all, strict=True)
    ]
    enc = tokenizer([words or [""] for words in words_all], is_split_into_words=True, add_special_tokens=False)
    items = []
    for doc_idx, units in enumerate(units_all):
        ids = enc["input_ids"][doc_idx]
        first = {}
        for tok_idx, word_idx in enumerate(enc.word_ids(doc_idx)):
            if word_idx is not None and word_idx not in first:
                first[word_idx] = tok_idx
        us = [u for u in range(len(units)) if u in first]
        if not us:
            continue
        tstart = [first[u] for u in us]
        tend = tstart[1:] + [len(ids)]
        for wa, wb, wc, wd in unit_windows(tstart, tend, max_len - 2, overlap):
            t0, t1 = tstart[wa], min(tend[wb - 1], tstart[wa] + max_len - 2)
            input_ids = [tokenizer.cls_token_id] + ids[t0:t1] + [tokenizer.sep_token_id]
            items.append({
                "doc": doc_idx,
                "input_ids": input_ids,
                "head_tok": [tstart[k] - t0 + 1 for k in range(wc, wd)],
                "head_unit": [us[k] for k in range(wc, wd)],
            })
    return units_all, items


class BamiBertNER:
    """Local GPU/CPU BamiBERT NER predictor."""

    def __init__(self, model_dir: str | Path, *, max_length: int = 2048,
                 window_overlap: int = 512, batch_size: int = 8, device: str = "auto"):
        import torch
        from transformers import (
            AutoModelForTokenClassification,
            AutoTokenizer,
            PreTrainedTokenizerFast,
        )

        model_path = Path(model_dir)
        if not model_path.exists():
            raise FileNotFoundError(f"Không tìm thấy checkpoint NER tại {model_path}")
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device
        self.max_length = max_length
        self.window_overlap = window_overlap
        self.batch_size = batch_size
        self._torch = torch
        tok_file = model_path / "tokenizer.json"
        if tok_file.is_file():
            tok_cfg = {}
            cfg_file = model_path / "tokenizer_config.json"
            if cfg_file.is_file():
                tok_cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            self.tokenizer = PreTrainedTokenizerFast(
                tokenizer_file=str(tok_file),
                bos_token=tok_cfg.get("bos_token", "<s>"),
                eos_token=tok_cfg.get("eos_token", "</s>"),
                cls_token=tok_cfg.get("cls_token", "<s>"),
                sep_token=tok_cfg.get("sep_token", "</s>"),
                pad_token=tok_cfg.get("pad_token", "<pad>"),
                unk_token=tok_cfg.get("unk_token", "<unk>"),
                mask_token=tok_cfg.get("mask_token", "<mask>"),
            )
        else:
            self.tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
        self.tokenizer.model_max_length = max_length
        self.model = AutoModelForTokenClassification.from_pretrained(
            str(model_path), local_files_only=True,
        ).to(device)
        self.model.eval()
        id2label = getattr(self.model.config, "id2label", None) or {}
        self.id2label = {int(k): v for k, v in id2label.items()} if id2label else dict(enumerate(BIO_LABELS))

    def predict_texts(self, texts: list[str]) -> list[list[dict]]:
        if not texts:
            return []
        torch = self._torch
        units_all, items = encode_texts(
            self.tokenizer, texts, max_len=self.max_length, overlap=self.window_overlap,
        )
        doc_tags = [["O"] * len(units) for units in units_all]
        pad_id = self.tokenizer.pad_token_id or 0
        ordered = sorted(range(len(items)), key=lambda i: -len(items[i]["input_ids"]))

        use_amp = self.device == "cuda"
        amp_dtype = torch.bfloat16 if (use_amp and torch.cuda.is_bf16_supported()) else torch.float16

        with torch.inference_mode():
            for start in range(0, len(ordered), self.batch_size):
                batch_idx = ordered[start:start + self.batch_size]
                batch = [items[i] for i in batch_idx]
                max_n = max(len(x["input_ids"]) for x in batch)
                ids = torch.full((len(batch), max_n), pad_id, dtype=torch.long)
                mask = torch.zeros((len(batch), max_n), dtype=torch.long)
                for row_i, item in enumerate(batch):
                    length = len(item["input_ids"])
                    ids[row_i, :length] = torch.tensor(item["input_ids"], dtype=torch.long)
                    mask[row_i, :length] = 1
                ids = ids.to(self.device)
                mask = mask.to(self.device)
                if use_amp:
                    with torch.autocast("cuda", dtype=amp_dtype):
                        logits = self.model(input_ids=ids, attention_mask=mask).logits
                else:
                    logits = self.model(input_ids=ids, attention_mask=mask).logits
                best = logits.argmax(-1).cpu().tolist()
                for item, row in zip(batch, best, strict=True):
                    doc_i = item["doc"]
                    for unit_idx, tok_idx in zip(item["head_unit"], item["head_tok"], strict=True):
                        doc_tags[doc_i][unit_idx] = self.id2label.get(row[tok_idx], "O")

        return [
            clean_entities(spans_from_bio(units, tags, text), text)
            for units, tags, text in zip(units_all, doc_tags, texts, strict=True)
        ]


def ner_from_config(ner_cfg: dict) -> BamiBertNER:
    """Dựng BamiBERT từ mục `ner` của configs/rag.yaml (một chỗ duy nhất đọc tham số)."""
    return BamiBertNER(
        ner_cfg["model_dir"],
        max_length=int(ner_cfg.get("max_length", 2048)),
        window_overlap=int(ner_cfg.get("window_overlap", 512)),
        batch_size=int(ner_cfg.get("batch_size", 8)),
        device=ner_cfg.get("device", "auto"),
    )


class SharedNER:
    """Một bản BamiBERT trên VRAM dùng chung cho mọi request và worker sync trong tiến trình.

    Nạp lười hoặc nạp trước bằng `load()`; nạp lỗi thì chỉ ghi tên lỗi (không ghi thông điệp
    có thể chứa đường dẫn) và thử lại ở lần gọi sau. Khoá tuần tự hoá cả nạp lẫn suy luận:
    model GPU không an toàn khi gọi song song từ nhiều thread.
    """

    def __init__(self, factory):
        self._factory = factory
        self._model = None
        self._lock = threading.Lock()
        self.error: str | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _ensure(self):
        if self._model is None:
            try:
                self._model = self._factory()
            except Exception as exc:
                self.error = type(exc).__name__
                raise
            self.error = None
        return self._model

    def load(self) -> bool:
        with self._lock:
            try:
                self._ensure()
            except Exception:  # noqa: BLE001 -- đã ghi tên lỗi; caller quyết định chạy tiếp
                return False
            return True

    def predict_texts(self, texts: list[str]) -> list[list[dict]]:
        with self._lock:
            return self._ensure().predict_texts(texts)
