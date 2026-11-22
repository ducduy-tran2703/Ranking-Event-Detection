import threading

from eventrank.rag.ner import (
    SharedNER,
    clean_entities,
    encode_texts,
    spans_from_bio,
    unit_spans,
    unit_windows,
)


class _FakeEnc:
    def __init__(self, input_ids, word_ids_list):
        self._data = {"input_ids": input_ids}
        self._word_ids = word_ids_list

    def __getitem__(self, key):
        return self._data[key]

    def word_ids(self, idx):
        return self._word_ids[idx]


class _FakeTokenizer:
    cls_token_id = 0
    sep_token_id = 2

    def __call__(self, batch_words, is_split_into_words=True, add_special_tokens=False):
        assert is_split_into_words and not add_special_tokens
        input_ids = []
        word_ids_list = []
        for words in batch_words:
            ids = []
            wids = []
            for wi, _word in enumerate(words):
                ids.extend([10 + wi, 100 + wi])
                wids.extend([wi, wi])
            input_ids.append(ids)
            word_ids_list.append(wids)
        return _FakeEnc(input_ids, word_ids_list)


def test_unit_spans_and_bio_to_entities():
    text = "Chiều 12/9, ông Phạm Minh Chính thăm Hà Nội."
    units = unit_spans(text)
    tags = ["O"] * len(units)
    words = [text[s:e] for s, e in units]
    i_pham = words.index("Phạm")
    tags[i_pham : i_pham + 3] = ["B-PER", "I-PER", "I-PER"]
    i_ha = words.index("Hà")
    tags[i_ha : i_ha + 2] = ["B-LOC", "I-LOC"]

    ents = spans_from_bio(units, tags, text)
    assert [(e["text"], e["label"]) for e in ents] == [
        ("Phạm Minh Chính", "PER"),
        ("Hà Nội", "LOC"),
    ]


def test_clean_entities_applies_guideline_rules():
    text = (
        "Tổng thống Donald Trump gặp bin Laden tại Nhà Trắng. "
        "UBND họp về Thông tư mới trên YouTube với cổ phiếu VND."
    )

    def span(sub, label):
        s = text.index(sub)
        return {"text": sub, "label": label, "start_char": s, "end_char": s + len(sub)}

    raw = [
        span("Tổng thống Donald Trump", "PER"),
        span("bin Laden", "PER"),
        span("Nhà Trắng", "LOC"),
        span("UBND", "ORG"),
        span("Thông tư", "DOC"),
        span("YouTube", "ORG"),
        span("VND", "ORG"),
    ]
    cleaned = clean_entities(raw, text)
    assert [(e["text"], e["label"]) for e in cleaned] == [
        ("Donald Trump", "PER"),
        ("bin Laden", "PER"),
        ("Nhà Trắng", "ORG"),
        ("YouTube", "PRODUCT"),
        ("VND", "ORG"),
    ]


def test_unit_windows_and_encode_texts_cover_all_units():
    windows = unit_windows([0, 3, 6, 9, 12], [3, 6, 9, 12, 15], budget=6, overlap=3)
    covered = []
    for _a, _b, c, d in windows:
        covered.extend(range(c, d))
    assert covered == [0, 1, 2, 3, 4]

    units_all, items = encode_texts(_FakeTokenizer(), ["Hà Nội hôm nay trời đẹp"], max_len=8, overlap=2)
    assert len(units_all[0]) == 6
    covered_units = []
    for item in items:
        assert len(item["input_ids"]) <= 8
        covered_units.extend(item["head_unit"])
    assert covered_units == [0, 1, 2, 3, 4, 5]


# ---------------------------------------------------------------- SharedNER: nạp một lần, dùng chung
class _CountingModel:
    def __init__(self):
        self.calls = 0

    def predict_texts(self, texts):
        self.calls += 1
        return [[] for _ in texts]


def test_shared_ner_chi_nap_model_mot_lan_cho_nhieu_request():
    built = []

    def factory():
        built.append(1)
        return _CountingModel()

    shared = SharedNER(factory)
    assert shared.loaded is False
    for _ in range(5):
        assert shared.predict_texts(['câu hỏi']) == [[]]
    assert built == [1]
    assert shared.loaded is True


def test_shared_ner_nap_song_song_van_chi_mot_ban():
    built = []
    gate = threading.Event()

    def factory():
        gate.wait(1)
        built.append(1)
        return _CountingModel()

    shared = SharedNER(factory)
    threads = [threading.Thread(target=shared.load) for _ in range(4)]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join()
    assert built == [1]


def test_shared_ner_nap_loi_ghi_ten_loi_va_thu_lai_lan_sau():
    attempts = []

    def factory():
        attempts.append(1)
        if len(attempts) == 1:
            raise ImportError('No module named torch (C:/private/path)')
        return _CountingModel()

    shared = SharedNER(factory)
    assert shared.load() is False
    assert shared.error == 'ImportError'
    assert shared.predict_texts(['x']) == [[]]
    assert shared.error is None and len(attempts) == 2
