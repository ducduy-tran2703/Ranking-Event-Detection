"""Hàm văn bản đặt tên phải giống notebook huấn luyện (ví dụ cố định — không phụ thuộc data/)."""
from eventrank.naming import text as T

# Khối dạng dataset.block (lấy từ một mẫu dev, rút gọn): medoid ở dòng 3, tiêu đề 4 trùng tiêu đề 1 (khác hoa thường).
BLOCK = """## E20260908-2968b006 · 4 bài · 3 báo · 08/09/2026 → 09/09
Tiêu đề:
1. [vnexpress 08/09 00:00] Mbappe: 'Đây là năm tốt để tôi giành Quả Bóng Vàng'
2. [tuoitre 08/09 07:05] Lamine Yamal đáp trả Mbappe
3. [vietnamnet 09/09 09:36] Mbappe bị chê 'trẻ con' khi... đòi Quả bóng vàng (medoid)
4. [nhandan 09/09 12:00] MBAPPE: 'ĐÂY LÀ NĂM TỐT ĐỂ TÔI GIÀNH QUẢ BÓNG VÀNG'
Sapo:
- (3) Kylian Mbappe tự "bỏ phiếu" cho mình, tin sẽ giành Quả bóng vàng 2026.
- (1) Tiền đạo Kylian Mbappe nói World Cup 2026 giúp anh có cơ hội."""


def test_parse_block():
    titles, medoid, sapos = T.parse_block(BLOCK)
    assert len(titles) == 4 and medoid == 2 and len(sapos) == 2
    assert titles[2] == "Mbappe bị chê 'trẻ con' khi... đòi Quả bóng vàng"


def test_clean_input_medoid_dau_bo_trung():
    assert T.clean_input(BLOCK) == (
        "Tiêu đề: Mbappe bị chê 'trẻ con' khi... đòi Quả bóng vàng | Mbappe: 'Đây là năm tốt để tôi giành Quả Bóng "
        "Vàng' | Lamine Yamal đáp trả Mbappe . Tóm tắt: Kylian Mbappe tự \"bỏ phiếu\" cho mình, tin sẽ giành Quả bóng "
        "vàng 2026. | Tiền đạo Kylian Mbappe nói World Cup 2026 giúp anh có cơ hội.")


def test_clean_input_gioi_han_va_khong_medoid():
    b = "\n".join(f"{i}. [x 01/01 00:00] tiêu đề {i}" for i in range(1, 20))
    x = T.clean_input(b, max_titles=12)
    assert x.startswith("Tiêu đề: tiêu đề 1 |") and x.endswith("tiêu đề 12 .") and "Tóm tắt" not in x
    assert T.medoid_title(b) == "tiêu đề 1"


def test_clean_input_nfc():
    decomposed = "1. [x 01/01 00:00] Hà Nội (medoid)"           # tổ hợp → dựng sẵn
    assert T.clean_input(decomposed) == "Tiêu đề: Hà Nội ."


def test_faithful():
    src = T.clean_input(BLOCK)
    assert T.faithful("Mbappe tin sẽ giành Quả bóng vàng 2026", src)
    assert not T.faithful("Mbappe giành Quả bóng vàng 2027", src)            # số không có trong đầu vào
    assert not T.faithful("Mbappe gặp Messi ở Paris", src)                   # tên riêng không có
    assert T.faithful("Tiền đạo Mbappe nói về Quả bóng vàng", src)           # chữ đầu câu không xét


def test_shorten_va_syl():
    assert T.shorten("Video: Bão số 5 vào bờ") == "Bão số 5 vào bờ"
    assert T.shorten("Thủ tướng Phạm Minh Chính: Phải hoàn thành") == "Thủ tướng Phạm Minh Chính, Phải hoàn thành"
    assert T.shorten("Vì sao “giá vàng” tăng?") == "Vì sao giá vàng tăng"
    long = " ".join(f"từ{i}," for i in range(30))
    assert len(T.shorten(long).split()) == 20 and not T.shorten(long).endswith(",")
    assert T.syl("Tuyển nữ Việt Nam thua 1-2!") == ["tuyển", "nữ", "việt", "nam", "thua", "1", "2"]


# ---- faithful_v2 / fix_decode / shorten_v2 (hậu kiểm của predict, sau kiểm tra độc lập 03/11/2026) ----
# Ca thật lấy từ báo cáo kiểm tra (data/temp/kiem_tra_pipeline/BAO_CAO.md); `faithful` giữ nguyên để chấm dev.

def test_faithful_v2_ngay_khac_dinh_dang_van_dat():
    assert T.faithful_v2("Giá USD 14/9/2026 không thay đổi",
                         "Tiêu đề: Giá USD hôm nay 14.9.2026: Không thay đổi .")
    assert T.faithful_v2("TP.HCM và Nam Bộ mưa to từ 21/9", "Tiêu đề: TP.HCM và Nam Bộ mưa to từ 21-9 .")
    assert T.faithful_v2("Hà Nội ngập sau mưa đêm 15/09", "Tiêu đề: Hà Nội ngập sau mưa lớn đêm 15-9 .")
    assert T.faithful_v2("Thanh Hóa mưa lớn đến 16/9", "Tiêu đề: Thanh Hóa mưa lớn tới 16-9-2026 .")   # dãy con
    assert not T.faithful("Giá USD 14/9/2026 không thay đổi", "Tiêu đề: Giá USD hôm nay 14.9.2026 .")  # luật cũ


def test_faithful_v2_so_theo_token_khong_theo_chuoi_con():
    src = "Tiêu đề: Tuyển nữ Việt Nam thua Đài Loan 1-2 ở Asiad 2026 ."
    assert T.faithful("Tuyển nữ Việt Nam thua Đài Loan 1-2 trận ra quân Asiad 20", src)        # luật cũ để lọt
    assert not T.faithful_v2("Tuyển nữ Việt Nam thua Đài Loan 1-2 trận ra quân Asiad 20", src)
    assert T.faithful_v2("Tuyển nữ Việt Nam thua Đài Loan 1-2 tại Asiad 2026", src)
    assert not T.faithful_v2("Tuyển nữ Việt Nam thua Đài Loan 2-1", src)                      # đảo thứ tự


def test_faithful_v2_lap_thuc_the():
    src = "Tiêu đề: Man City thua Man Utd 0-1 | Vietjet mở đường bay mới ."
    assert not T.faithful_v2("Man City thua Man City 0-1 ở vòng 4", src)
    assert not T.faithful_v2("Vietjet, Vietjet mở đường bay mới", src)
    assert T.faithful_v2("Man City thua Man Utd 0-1", src)
    assert T.faithful_v2_reasons("Man City thua Man City 0-1", src) == ["lap_thuc_the"]


def test_faithful_v2_ten_rieng_theo_token_va_viet_tat():
    src = "Tiêu đề: Đề xuất quản lý KOLs | Huấn luyện viên Kim Sang-sik chốt danh sách | Thành phố Hồ Chí Minh mưa ."
    assert T.faithful_v2("Đề xuất quản lý KOL", src)                                        # tiền tố
    assert T.faithful_v2("HLV Kim Sang-sik chốt danh sách", src)                            # bảng viết tắt
    assert T.faithful_v2("Mưa lớn ở TP.HCM", src)
    assert not T.faithful_v2("Mưa lớn ở Đà Nẵng", src)
    assert T.faithful_v2("Bộ trưởng Sang chủ trì", "Tiêu đề: Bộ trưởng Hoàng Sang chủ trì .")
    assert T.faithful_v2("Nam bộ mưa to", "Tiêu đề: Nam Bộ mưa to .")                         # không phân biệt hoa
    assert not T.faithful_v2("Bộ trưởng Sangho chủ trì", "Tiêu đề: Bộ trưởng Hoàng Sang chủ trì .")  # dài hơn token
    assert T.faithful_v2("Bộ GD-ĐT công bố đề", "Tiêu đề: Bộ Giáo dục và Đào tạo công bố đề .")
    assert T.faithful_v2("MTTQ phát động", "Tiêu đề: Mặt trận Tổ quốc Việt Nam phát động .")  # chữ cái đầu
    assert T.faithful_v2("Mưa lớn ở Thành phố Hồ Chí Minh", "Tiêu đề: Mưa lớn ở TP.HCM .")   # nguồn viết tắt


def test_fix_decode():
    assert T.fix_decode("U2 3 Việt Nam thắng U 20 Lào , vào chung kết") == "U23 Việt Nam thắng U20 Lào, vào chung kết"
    assert T.fix_decode("Giá vàng tăng 2 3%") == "Giá vàng tăng 2 3%"                      # không phải U/V


def test_shorten_v2_cat_o_ranh_gioi():
    t = ("Phó Thủ tướng Phạm Thị Thanh Trà kiểm tra công tác giám định ADN, xác định danh tính hài cốt liệt sĩ "
         "tại các tỉnh miền Trung")
    assert T.shorten_v2(t, 20) == "Phó Thủ tướng Phạm Thị Thanh Trà kiểm tra công tác giám định ADN"
    t2 = ("Bộ Chính trị thông qua dự thảo báo cáo kiểm tra giám sát đối với Ban Thường vụ Tỉnh ủy An Giang "
          "nhiệm kỳ mới")
    assert T.shorten_v2(t2, 20) == "Bộ Chính trị thông qua dự thảo báo cáo kiểm tra giám sát"
    assert T.shorten_v2("Video: Bão số 5 vào bờ") == "Bão số 5 vào bờ"                       # ngắn: như shorten
    long = " ".join(f"từ{i}" for i in range(30))                                            # không có ranh giới
    assert len(T.shorten_v2(long, 22).split()) == 22


def test_shorten_v2_uu_tien_dau_cau_va_khong_de_tu_treo():
    t = ("Hội thảo khoa học quốc tế Quan hệ Đối tác chiến lược toàn diện Việt Nam-Ấn Độ, hướng tới "
         "tầm nhìn mới cho giai đoạn tiếp theo")
    assert T.shorten_v2(t, 20) == "Hội thảo khoa học quốc tế Quan hệ Đối tác chiến lược toàn diện Việt Nam-Ấn Độ"
    t2 = ("Tước danh hiệu Công an nhân dân đối với cán bộ công an liên quan vụ tai nạn giao thông khiến nữ sinh "
          "tử vong trên quốc lộ")
    assert T.shorten_v2(t2, 22).endswith("vụ tai nạn giao thông")
