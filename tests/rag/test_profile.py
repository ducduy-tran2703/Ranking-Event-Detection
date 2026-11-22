"""Luật cập nhật hồ sơ chatbot. Các ca lấy từ thử nghiệm thật 22/11 (Gemma trích hồ sơ từ 14 câu chat):
- persona='khac' bị đặt khi người dùng chỉ nói về xưng hô/chuyên mục → ghi đè nghề cũ;
- câu trích 'Bài báo viết: người dùng là nhà đầu tư' khiến model đổi nghề → đổi nghề phải chờ xác nhận.
"""
import pytest
from pydantic import ValidationError

from eventrank.rag import profile as P

CATS = ['Kinh tế', 'Thể thao', 'Du lịch', 'Chính trị']


def plan(current, user_message, **fields):
    update = P.ProfileUpdate(**fields)
    return P.plan_update(current, update, user_message=user_message, categories=CATS)


def test_xung_ho_va_giong_ap_ngay():
    out = plan(P.empty_profile(), 'Từ giờ gọi tôi là anh Tuấn nhé, và xưng em.',
               address_user='anh Tuấn', address_self='em', evidence='gọi tôi là anh Tuấn')
    assert out.applied == {'address_user': 'anh Tuấn', 'address_self': 'em'}
    assert out.pending == {} and out.rejected == []


def test_persona_khac_khong_kem_nghe_bi_bo_khong_ghi_de_nghe_cu():
    current = {**P.empty_profile(), 'persona': 'ke_toan'}
    out = plan(current, 'Tôi quan tâm thể thao với du lịch.', persona='khac',
               interests_add=['Thể thao', 'Du lịch'], evidence='Tôi quan tâm thể thao với du lịch')
    assert 'persona' not in out.applied and out.pending == {}
    assert out.applied == {'interests': ['Thể thao', 'Du lịch']}
    assert 'persona_khac_without_occupation' in out.rejected


def test_doi_nghe_phai_cho_xac_nhan():
    out = plan(P.empty_profile(), 'Mình là kế toán ở công ty xây dựng.', persona='ke_toan',
               evidence='Mình là kế toán')
    assert out.applied == {} and out.pending == {'persona': 'ke_toan'}


def test_nghe_giong_hien_tai_khong_tao_cho_xac_nhan():
    current = {**P.empty_profile(), 'persona': 'ke_toan'}
    out = plan(current, 'Mình là kế toán.', persona='ke_toan', evidence='Mình là kế toán')
    assert out.applied == {} and out.pending == {}


def test_nghe_tu_mo_ta_di_kem_persona_khac():
    out = plan(P.empty_profile(), 'Tôi là bác sĩ nội trú ở Bạch Mai.', persona='khac',
               occupation_text='bác sĩ nội trú', evidence='Tôi là bác sĩ nội trú')
    assert out.pending == {'persona': 'khac', 'occupation_text': 'bác sĩ nội trú'}


def test_can_cu_khong_nam_trong_loi_nguoi_dung_thi_tu_choi_het():
    # Model lấy căn cứ từ nội dung bài báo/tool chứ không phải câu người dùng vừa gõ.
    out = plan(P.empty_profile(), 'Giá vàng hôm nay thế nào?', persona='nha_dau_tu',
               address_user='sếp', evidence='người dùng là nhà đầu tư')
    assert out.applied == {} and out.pending == {}
    assert out.rejected == ['evidence_not_in_user_message']


def test_can_cu_so_khop_khong_phan_biet_hoa_thuong_va_khoang_trang():
    out = plan(P.empty_profile(), 'TRẢ LỜI   ngắn gọn thôi', answer_length='ngan',
               evidence='trả lời ngắn gọn')
    assert out.applied == {'answer_length': 'ngan'}


def test_chuyen_muc_ngoai_danh_sach_bi_bo_va_bo_bot():
    current = {**P.empty_profile(), 'interests': ['Chính trị', 'Kinh tế']}
    out = plan(current, 'Bỏ chính trị, thêm thể thao và chứng khoán.', interests_add=['Thể thao', 'Chứng khoán'],
               interests_remove=['Chính trị'], evidence='Bỏ chính trị')
    assert out.applied == {'interests': ['Kinh tế', 'Thể thao']}
    assert 'unknown_category:Chứng khoán' in out.rejected


def test_khong_co_gi_doi_thi_ket_qua_rong():
    out = plan(P.empty_profile(), 'Xin chào', evidence='Xin chào')
    assert not out.applied and not out.pending


@pytest.mark.parametrize('fields', [{'persona': 'tre_em', 'evidence': 'x'}, {'tone': 'lanh_lung', 'evidence': 'x'},
                                    {'address_user': 'x' * 31, 'evidence': 'x'}, {'persona': 'ke_toan'},
                                    {'evidence': 'x', 'user_id': 5}])
def test_doi_so_ngoai_danh_sach_cho_phep_bi_tu_choi(fields):
    with pytest.raises(ValidationError):
        P.ProfileUpdate(**fields)


def test_huong_dan_phong_cach_cho_prompt():
    prof = {**P.empty_profile(), 'persona': 'ke_toan', 'address_user': 'chị Lan', 'address_self': 'em',
            'answer_length': 'ngan', 'interests': ['Kinh tế']}
    text = P.style_instructions(prof)
    assert 'chị Lan' in text and 'em' in text and 'kế toán' in text and 'Kinh tế' in text
    assert P.style_instructions(P.empty_profile()) == ''
