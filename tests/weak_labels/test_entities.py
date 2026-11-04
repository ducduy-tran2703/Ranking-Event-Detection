from eventrank.weak_labels.entities import (
    EntityNormalizer,
    article_entities,
    entity_key,
    zone_bounds,
)

ALIASES = {"thànhphốhồchíminh": "tphcm", "trump": "donaldtrump"}


def test_khoa_gop_bien_the_hoa_thuong_dau_cham_khoang_trang():
    assert entity_key("TP.HCM") == entity_key("TP HCM") == entity_key("TPHCM") == "tphcm"
    assert entity_key("Kim Sang-sik") == entity_key("Kim Sang Sik")


def test_khoa_chuan_hoa_nfd_ve_nfc():
    nfd = "Hà Nội"          # "Hà Nội" dạng NFD
    assert entity_key(nfd) == entity_key("Hà Nội")


def test_alias_gop_ten_khac_nhau_cua_cung_thuc_the():
    n = EntityNormalizer(ALIASES)
    assert n.norm("Thành phố Hồ Chí Minh", "LOC") == n.norm("TP.HCM", "LOC") == "tphcm"
    assert n.norm("Trump", "PER") == n.norm("Donald Trump", "PER") == "donaldtrump"


def test_bo_tien_to_hanh_chinh_cua_dia_danh():
    n = EntityNormalizer({})
    assert n.norm("tỉnh An Giang", "LOC") == n.norm("An Giang", "LOC")
    assert n.norm("thành phố Đà Nẵng", "LOC") == n.norm("Đà Nẵng", "LOC")


def test_tp_hcm_khong_bi_nham_voi_ten_nguoi_ho_chi_minh():
    n = EntityNormalizer(ALIASES)
    assert n.norm("Thành phố Hồ Chí Minh", "LOC") != n.norm("Hồ Chí Minh", "PER")


def test_van_ban_gop_theo_loai_va_so_hieu():
    n = EntityNormalizer({})
    keys = {n.norm(t, "DOC") for t in
            ["Nghị quyết 57", "Nghị quyết số 57-NQ/TW", "Nghị quyết 57-NQ/TW", "nghị quyết số 57"]}
    assert len(keys) == 1


def test_loai_thuc_the_rac():
    n = EntityNormalizer({})
    for text, label in [('"', "ORG"), ("-", "LOC"), ("2026", "DOC"), ("ủy", "ORG"),
                        ("tỉnh", "ORG"), ("Công an", "ORG")]:
        assert n.norm(text, label) is None, text


def test_cat_dau_cau_dinh_o_bien():
    n = EntityNormalizer({})
    assert n.norm("Việt Nam -", "LOC") == n.norm("Việt Nam", "LOC")
    assert n.norm("Cục Dự trữ Liên bang Mỹ (", "ORG") == n.norm("Cục Dự trữ Liên bang Mỹ", "ORG")


def _article(title, sapo, content, entities, source="tuoitre"):
    return {"source": source, "title": title, "sapo": sapo, "content_text": content,
            "entities": entities}


def _span(full, text, label, nth=0):
    start = -1
    for _ in range(nth + 1):
        start = full.index(text, start + 1)
    return {"text": text, "label": label, "start_char": start, "end_char": start + len(text)}


def _full(title, sapo, content):
    return f"Tiêu đề: {title}\n\nSapo: {sapo}\n\nNội dung:\n{content}"


def test_vung_cua_van_ban_ghep_dung_khuon():
    full = _full("ABC", "DE", "xyz")
    b = zone_bounds("ABC", "DE")
    assert full[b.title[0]:b.title[1]] == "ABC"
    assert full[b.sapo[0]:b.sapo[1]] == "DE"
    assert full[b.content_start:] == "xyz"


def test_thuc_the_trong_tieu_de_noi_bat_hon_thuc_the_cuoi_bai():
    title, sapo = "Bão Yagi đổ bộ Quảng Ninh", "Sáng nay bão Yagi vào bờ."
    content = "Mưa lớn. " * 200 + "Ông Nguyễn Văn A nói."
    full = _full(title, sapo, content)
    art = _article(title, sapo, content, [
        _span(full, "Yagi", "EVENT"), _span(full, "Yagi", "EVENT", nth=1),
        _span(full, "Quảng Ninh", "LOC"), _span(full, "Nguyễn Văn A", "PER")])
    ents = article_entities(art, EntityNormalizer({}))
    assert ents["yagi"].in_head and ents["yagi"].mentions == 2
    assert ents["nguyễnvăna"].in_head is False
    assert ents["yagi"].salience > ents["quảngninh"].salience > ents["nguyễnvăna"].salience


def test_bo_ten_chinh_to_bao_dang_bai():
    title, sapo, content = "Tuổi Trẻ đưa tin", "Theo Tuổi Trẻ", "Hà Nội mưa."
    full = _full(title, sapo, content)
    art = _article(title, sapo, content,
                   [_span(full, "Tuổi Trẻ", "ORG"), _span(full, "Hà Nội", "LOC")],
                   source="tuoitre")
    ents = article_entities(art, EntityNormalizer({}))
    assert "tuổitrẻ" not in ents and "hànội" in ents
    # Báo khác nhắc Tuổi Trẻ thì vẫn giữ
    art["source"] = "vnexpress"
    assert "tuổitrẻ" in article_entities(art, EntityNormalizer({}))


def test_ten_nguoi_mot_chu_khong_co_ten_day_du_trong_bai_bi_ha_trong_so():
    title, sapo, content = "Anh Tuấn và chị Lan Phương", "", ""
    full = _full(title, sapo, content)
    art = _article(title, sapo, content,
                   [_span(full, "Tuấn", "PER"), _span(full, "Lan Phương", "PER")])
    ents = article_entities(art, EntityNormalizer({}))
    assert ents["tuấn"].salience < ents["lanphương"].salience


def test_ten_mot_chu_noi_voi_ten_day_du_trong_cung_bai():
    # "Nguyễn Văn Tuấn ... ông Tuấn cho biết" → cùng một người
    title, sapo, content = "Nguyễn Văn Tuấn nhận giải", "Ông Tuấn cho biết rất vui.", ""
    full = _full(title, sapo, content)
    art = _article(title, sapo, content,
                   [_span(full, "Nguyễn Văn Tuấn", "PER"), _span(full, "Tuấn", "PER", nth=1)])
    ents = article_entities(art, EntityNormalizer({}))
    assert set(ents) == {"nguyễnvăntuấn"} and ents["nguyễnvăntuấn"].mentions == 2


def test_ten_mot_chu_mo_ho_giua_hai_nguoi_thi_khong_noi():
    title, sapo, content = "Nguyễn Văn Tuấn và Lê Anh Tuấn", "Tuấn nói.", ""
    full = _full(title, sapo, content)
    art = _article(title, sapo, content,
                   [_span(full, "Nguyễn Văn Tuấn", "PER"), _span(full, "Lê Anh Tuấn", "PER"),
                    _span(full, "Tuấn", "PER", nth=2)])
    ents = article_entities(art, EntityNormalizer({}))
    assert "tuấn" in ents and ents["nguyễnvăntuấn"].mentions == 1


def test_giu_ten_nuoc_mot_chu_cai():
    n = EntityNormalizer({})
    assert n.norm("Ý", "LOC") == "ý" and n.norm("Á", "LOC") == "á"
    assert n.norm("X", "PRODUCT") is None              # quá mơ hồ khi đứng một mình


def test_tu_chung_khong_ap_cho_ten_nguoi():
    n = EntityNormalizer({})
    assert n.norm("Trường", "PER") == "trường"
    assert n.norm("Trường", "ORG") is None


def test_giu_thuong_hieu_viet_thuong_bo_manh_tu_tieng_viet():
    n = EntityNormalizer({})
    assert n.norm("adidas", "ORG") == "adidas" and n.norm("vivo", "ORG") == "vivo"
    for frag in ["thành", "quan", "khu", "phòng", "trưởng"]:
        assert n.norm(frag, "ORG") is None, frag


def test_dac_khu_la_tien_to_hanh_chinh():
    n = EntityNormalizer({})
    assert n.norm("Đặc khu Trường Sa", "LOC") == n.norm("Trường Sa", "LOC")


def test_bo_cap_hanh_chinh_o_giua_ten_co_quan():
    n = EntityNormalizer({})
    assert n.norm("Sở Y tế tỉnh Gia Lai", "ORG") == n.norm("Sở Y tế Gia Lai", "ORG")
    assert n.norm("UBND thành phố Hà Nội", "ORG") == n.norm("UBND Hà Nội", "ORG")
