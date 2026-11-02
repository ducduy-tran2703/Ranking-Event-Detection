import numpy as np

from eventrank.weak_labels.graded import (
    EXCLUDED,
    GREY,
    LEVEL_SCORE,
    bucket_of,
    is_roundup,
    parse_level,
    rule_levels,
    weighted_level_shares,
)
from eventrank.weak_labels.pairs import FEATURES


def _f(**kw):
    f = {k: np.zeros(1) for k in FEATURES}
    f["cos_dense"] = np.full(1, np.nan)
    f["p"] = np.zeros(1)
    for k, v in kw.items():
        f[k] = np.array([v], dtype=float)
    return f


def _lv(title_a="A", title_b="B", **kw):
    return int(rule_levels(_f(**kw), [title_a], [title_b])[0])


def test_thang_diem_4_muc():
    assert LEVEL_SCORE == {3: 1.0, 2: 0.6, 1: 0.3, 0: 0.0}


def test_cung_su_kien_khi_p_cao():
    assert _lv(p=0.94, cos_head=0.5, ent_wjacc=0.4) == 3


def test_chuoi_bai_dinh_ky_khac_ngay_la_cung_khuon_tin():
    # "Giá vàng hôm nay 15/9" ↔ "Giá vàng hôm nay 10/9": p bị phủ quyết, cùng chuyên mục, tiêu đề cùng khuôn
    similar = {"cos_lead": 0.3, "ent_wjacc": 0.3}          # hai bài cùng khuôn: trùng chữ và thực thể khá
    assert _lv(p=0.02, date_conflict=1, same_category=1, cos_head=0.26, **similar) == 1
    # khác chuyên mục hoặc tiêu đề không cùng khuôn → không tự gán, để Claude xem
    assert _lv(p=0.02, date_conflict=1, same_category=0, cos_head=0.26, **similar) == GREY
    assert _lv(p=0.02, date_conflict=1, same_category=1, cos_head=0.05, **similar) == GREY


def test_cung_khuon_tin_khac_doi_tuong_khong_tu_gan_ma_de_claude_gan():
    # Đo trên tập tune v4 (24 cặp, Claude gán mù): luật "khuôn tin" chỉ đúng mức 1 ở 62%; 21% là CÙNG SỰ KIỆN
    # (các hoạt động của cùng một chuyến thăm: "hội kiến Medvedev" ↔ "hội kiến Matvienko") → gán 0,3 sẽ dạy mô
    # hình đẩy chúng ra xa. Nên luật không gán; tầng riêng g_template để Claude gán.
    f = {"p": 0.18, "conflict_org": 1, "cos_head": 0.33, "n_head_shared": 0, "same_category": 1,
         "cos_lead": 0.25, "ent_wjacc": 0.02}
    assert _lv(**f) == GREY
    assert bucket_of(GREY, {"date_conflict": 0, "n_head_shared": 0, "p": 0.18, "template": 1}) == "g_template"


def test_khong_lien_quan_khi_khac_ca_chu_lan_thuc_the():
    assert _lv(p=0.02, cos_lead=0.05, ent_wjacc=0.02) == 0
    # cùng nghĩa (embedding gần) dù khác chữ → không tự gán 0
    assert _lv(p=0.02, cos_lead=0.05, ent_wjacc=0.02, cos_dense=0.7) == GREY
    # p không thấp → không tự gán 0
    assert _lv(p=0.3, cos_lead=0.05, ent_wjacc=0.02) == GREY


def test_vung_xam_de_claude_gan():
    assert _lv(p=0.5, cos_head=0.3, ent_wjacc=0.3, n_head_shared=1) == GREY


def test_bai_tong_hop_bi_loai():
    assert is_roundup("Tin tức thế giới 13-9: Lãnh đạo Trung - Ấn cam kết về biên giới")
    assert is_roundup("Tin tức sáng 18-9: TP.HCM sẽ kiểm tra đột xuất an toàn thực phẩm")
    assert is_roundup("Kết quả bóng đá hôm nay 13/9")
    assert is_roundup("Lịch thi đấu bóng đá hôm nay 13/9")
    assert is_roundup("Điểm tin sáng: giá xăng tăng")
    assert not is_roundup("Kết quả xét xử vụ án Mường Thanh")
    assert not is_roundup("U23 Việt Nam thắng U23 Kuwait")
    assert _lv("Tin tức thế giới 13-9: Mỹ buộc 100 tàu", "Thủ tướng tới New Delhi", p=0.94) == EXCLUDED


def test_doc_nhan_claude():
    assert parse_level("3") == 3 and parse_level(" 0 ") == 0
    assert parse_level("x") == EXCLUDED
    assert parse_level("?") is None and parse_level("") is None and parse_level("5") is None


def test_ti_le_tung_muc_co_trong_so_theo_tang():
    # tầng A: 1.000 cặp, mẫu 2 cặp đều mức 3; tầng B: 9.000 cặp, mẫu 2 cặp đều mức 0
    rows = {"A": [3, 3], "B": [0, 0]}
    shares = weighted_level_shares(rows, {"A": 1000, "B": 9000})
    assert abs(shares[3] - 0.1) < 1e-9 and abs(shares[0] - 0.9) < 1e-9


def test_kappa_4_muc():
    from eventrank.weak_labels.graded import kappa
    a = [3, 2, 1, 0, 3, 2, 1, 0]
    assert kappa(a, a) == 1.0
    lech_1_muc = [3, 1, 1, 0, 3, 2, 0, 0]       # hai cặp lệch đúng 1 mức
    lech_3_muc = [0, 2, 1, 0, 0, 2, 1, 0]       # hai cặp lệch 3 mức (3 → 0)
    # κ không trọng số coi mọi lệch như nhau; κ trọng số bậc hai phạt lệch xa nặng hơn
    assert kappa(a, lech_1_muc) == kappa(a, lech_3_muc)
    assert kappa(a, lech_1_muc, weights="quadratic") > kappa(a, lech_3_muc, weights="quadratic")
    # tính tay: po = 6/8 = 0,75; a chia đều 2/8 mỗi mức → pe = Σ 0,25 × p_b(c) = 0,25 → κ = 0,5 / 0,75 = 2/3
    assert abs(kappa(a, lech_1_muc) - 2 / 3) < 1e-9


def test_chon_cap_gan_lai_theo_huong_dan_moi():
    # Người duyệt 100 cặp (13/10): 5/6 lần sửa là NÂNG mức, chủ yếu 2→3 trong cùng chuyến đi / đợt tập trung →
    # gán lại mọi cặp mức 2, và mức 1 ở vùng chung thực thể (g_story) hoặc cùng khuôn tin (g_template)
    from eventrank.weak_labels.graded import needs_relabel
    assert needs_relabel(2, "g_mid") and needs_relabel(2, "g_low")
    assert needs_relabel(1, "g_story") and needs_relabel(1, "g_template")
    assert not needs_relabel(1, "g_mid") and not needs_relabel(1, "g_low")
    assert not needs_relabel(3, "g_story") and not needs_relabel(0, "g_story")


def test_chon_cap_cung_noi_dung_khac_chu():
    # Trong 7.673 cặp mức 3 của train v4 chỉ 11% có cos_head < 0,2 → mô hình fine-tune không tăng recall ở tầng
    # khác chữ. Trong vùng dưới đây (649 cặp Claude đã gán): 26% mức 3, 16% mức 2 → nguồn cặp khó cần gán thêm.
    from eventrank.weak_labels.graded import hard_mask
    base = {"cos_head": 0.1, "dt_hours": 20, "cross_source": 1, "p": 0.3, "cos_dense": 0.75,
            "ent_wjacc": 0.0, "n_head_shared": 0}
    assert _hm(hard_mask, base)
    assert not _hm(hard_mask, base | {"cos_head": 0.35})          # trùng chữ nhiều → không phải cặp "khác chữ"
    assert not _hm(hard_mask, base | {"dt_hours": 60})            # cách quá 48h
    assert not _hm(hard_mask, base | {"cross_source": 0})         # cùng báo
    assert not _hm(hard_mask, base | {"p": 0.9})                  # luật đã chắc là mức 3
    assert not _hm(hard_mask, base | {"cos_dense": 0.4})          # không có tín hiệu cùng nội dung nào
    assert _hm(hard_mask, base | {"cos_dense": 0.4, "ent_wjacc": 0.25})   # chung thực thể thay cho embedding
    assert _hm(hard_mask, base | {"cos_dense": float("nan"), "n_head_shared": 1})


def _hm(fn, row):
    f = {k: np.array([v], dtype=float) for k, v in row.items()}
    return bool(fn(f)[0])


def test_ngay_o_dau_sapo():
    from eventrank.weak_labels.graded import lead_date
    assert lead_date("VBA 2026: Cantho Catfish tiến vào Top 4. Tối 18/7, dù vướng phải khó khăn") == (18, 7)
    assert lead_date("Lịch trực tiếp U20. Lúc 19h hôm nay 6-9, U20 Việt Nam sẽ gặp Iran") == (6, 9)
    assert lead_date("Tiêu đề không có sapo") is None
    assert lead_date("Tiêu đề. Sapo không nhắc ngày nào cả") is None


def test_chon_cap_muc_3_can_ra_lai_theo_quy_tac_29_10():
    # Rà tay 29/10/2026: luật gán mức 3 cho hai TRẬN khác nhau (U20 VN–Iran 6/9 ↔ –Palestine 3/9; Cantho Catfish 18/7
    # ↔ 16/7), hai NGƯỜI ở hai NƯỚC (Trần Thanh Mẫn ở Hàn Quốc ↔ Tô Lâm ở Nga); Claude gán mức 3 cho hai cuộc gặp khác
    # nhau của cùng chuyến (quy tắc cũ 13/10). Quét train: 1.872 / 8.066 cặp mức 3 có ít nhất một dấu hiệu dưới.
    from eventrank.weak_labels.graded import needs_recheck
    base = {"conflict_per": 0, "conflict_loc": 0, "dt_hours": 5}
    assert needs_recheck(3, "A. Tối 18/7, Cantho thắng", "B. Tối 16/7, Cantho thắng", base)        # khác ngày ở sapo
    assert needs_recheck(3, "A. sapo", "B. sapo", base | {"conflict_per": 1})                      # khác người
    assert needs_recheck(3, "A. sapo", "B. sapo", base | {"conflict_loc": 1})                      # khác nơi
    assert needs_recheck(3, "A. sapo", "B. sapo", base | {"dt_hours": 40})                         # cách ≥ 30h
    assert not needs_recheck(3, "A. Tối 9/9, họp", "B. Chiều 9/9, họp", base)                     # cùng ngày, không dấu hiệu
    assert not needs_recheck(2, "A. Tối 18/7", "B. Tối 16/7", base)                                # chỉ rà mức 3
    # mức 0 do luật nhưng hai tiêu đề chung một tên riêng trong ngoặc kép ("Tổ quốc trong tim")
    assert needs_recheck(0, "Màn diễu binh trong chương trình \"Tổ quốc trong tim\". sapo",
                         "TP.HCM bắn pháo hoa tại chương trình 'Tổ quốc trong tim'. sapo", base)
    assert not needs_recheck(0, "Giá vàng hôm nay. sapo", "U20 Việt Nam thua. sapo", base)


def _e(a, b):
    return frozenset((a, b))


def test_mau_thuan_bac_cau():
    # Sau recheck 29/10: 431 tam giác "A–B = 3, A–X = 3 nhưng B–X = 2" trong train (62 trước recheck) — cạnh cùng ngày
    # của cùng chuyến thăm không bị needs_recheck chọn nên vẫn mang mức 3 theo quy tắc cũ.
    from eventrank.weak_labels.graded import transitivity_conflicts
    lv = {_e("A", "B"): 3, _e("A", "X"): 3, _e("B", "X"): 2,      # mâu thuẫn
          _e("C", "D"): 3, _e("C", "E"): 3, _e("D", "E"): 3,      # nhất quán
          _e("F", "G"): 3, _e("F", "H"): 2, _e("G", "H"): 2}      # nhất quán (3–2–2 được phép)
    assert transitivity_conflicts(lv) == {_e("A", "B"), _e("A", "X"), _e("B", "X")}
    assert transitivity_conflicts({_e("A", "B"): 3, _e("A", "X"): 3, _e("B", "X"): 0}) == {
        _e("A", "B"), _e("A", "X"), _e("B", "X")}
    assert transitivity_conflicts({_e("A", "B"): 3, _e("A", "X"): 3}) == set()   # thiếu cạnh thứ ba: không biết


def test_gom_nhom_cap_mau_thuan():
    # Gán cả nhóm cùng lúc để Claude thấy mọi cạnh giữa các bài của nhóm (kể cả cạnh không mâu thuẫn) và giữ bắc cầu
    from eventrank.weak_labels.graded import conflict_groups
    lv = {_e("A", "B"): 3, _e("A", "X"): 3, _e("B", "X"): 2, _e("X", "Y"): 1,
          _e("B", "Y"): 3, _e("P", "Q"): 3, _e("P", "R"): 3, _e("Q", "R"): 2, _e("Z", "W"): 3}
    groups = conflict_groups(lv, {_e("A", "B"), _e("A", "X"), _e("B", "X"), _e("P", "Q"), _e("P", "R"), _e("Q", "R")})
    as_sets = sorted((set(g) for g in groups), key=len, reverse=True)
    assert as_sets[0] == {_e("A", "B"), _e("A", "X"), _e("B", "X")}    # X–Y, B–Y: Y không thuộc nhóm
    assert as_sets[1] == {_e("P", "Q"), _e("P", "R"), _e("Q", "R")}
    assert len(groups) == 2
