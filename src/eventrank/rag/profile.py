"""Hồ sơ cá nhân hoá chatbot RAG (bảng rag_user_profiles, migration 010).

Hồ sơ chỉ đổi CÁCH trả lời (xưng hô, giọng, độ dài, nhấn mạnh theo nghề) và tin ưu tiên khi hỏi chung chung;
không bao giờ đổi sự thật, số liệu hay trích dẫn.

Luật cập nhật (bằng chứng: thử Gemma trích hồ sơ từ 14 câu chat, 22/11/2026):
- `evidence` phải là đoạn nằm trong CHÍNH câu người dùng vừa gõ; không thì bỏ cả cập nhật (chặn nội dung bài báo
  hoặc kết quả tool lừa model đổi hồ sơ).
- persona='khac' mà không kèm nghề tự mô tả → bỏ (model hay đặt 'khac' khi người dùng chỉ nói về xưng hô).
- Đổi nghề/nhóm (persona, occupation_text) → chỉ ghi vào `pending`, áp khi người dùng xác nhận.
- Xưng hô, giọng, độ dài, chuyên mục → áp ngay (người dùng thấy ngay ở câu trả lời và sửa lại được).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Annotated, Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Persona = Literal['pho_thong', 'doanh_nhan', 'ke_toan', 'nha_dau_tu', 'sinh_vien', 'giao_vien',
                  'can_bo_cong_chuc', 'nha_bao', 'lap_trinh_vien', 'khac']
Tone = Literal['than_thien', 'trang_trong', 'ngan_gon']
Length = Literal['ngan', 'vua', 'chi_tiet']
PERSONA_LABELS = {
    'pho_thong': 'người dùng phổ thông', 'doanh_nhan': 'doanh nhân', 'ke_toan': 'kế toán',
    'nha_dau_tu': 'nhà đầu tư', 'sinh_vien': 'sinh viên', 'giao_vien': 'giáo viên',
    'can_bo_cong_chuc': 'cán bộ, công chức', 'nha_bao': 'nhà báo', 'lap_trinh_vien': 'lập trình viên',
    'khac': 'nghề khác',
}
# Trọng tâm gợi ý theo nhóm: chỉ để CHỌN/NHẤN ý có trong bằng chứng, không thêm phân tích/lời khuyên.
PERSONA_FOCUS = {
    'doanh_nhan': 'ưu tiên ý về kinh doanh, thị trường, chính sách ảnh hưởng doanh nghiệp nếu bài có nêu',
    'ke_toan': 'nêu chính xác số hiệu văn bản, mức thuế/phí, ngày hiệu lực nếu bài có nêu',
    'nha_dau_tu': 'nêu chính xác số liệu thị trường, giá, tỷ lệ nếu bài có nêu',
    'sinh_vien': 'giải thích dễ hiểu, nêu bối cảnh có trong bài',
    'giao_vien': 'trình bày mạch lạc, dễ hiểu',
    'can_bo_cong_chuc': 'ưu tiên ý về chính sách, văn bản, cơ quan ban hành nếu bài có nêu',
}
TONE_LABELS = {'than_thien': 'thân thiện, gần gũi', 'trang_trong': 'trang trọng, lịch sự', 'ngan_gon': 'ngắn gọn, đi thẳng vào ý'}
LENGTH_LABELS = {'ngan': 'ngắn (2–3 ý)', 'vua': 'vừa phải', 'chi_tiet': 'chi tiết'}
STYLE_FIELDS = ('address_user', 'address_self', 'tone', 'answer_length')
IDENTITY_FIELDS = ('persona', 'occupation_text')
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]


class ProfileUpdate(BaseModel):
    """Đối số của tool `update_user_profile`. Không có user_id: luôn lấy từ phiên đăng nhập."""
    model_config = ConfigDict(extra='forbid')
    persona: Persona | None = Field(None, description='Nhóm người dùng gần nhất; nghề không khớp → "khac" kèm occupation_text.')
    occupation_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None = Field(
        None, description='Nghề người dùng tự nói, khi persona = "khac".')
    address_user: Short | None = Field(None, description='Cách người dùng muốn được gọi, ví dụ "anh Tuấn", "chị", "bạn".')
    address_self: Short | None = Field(None, description='Cách chatbot tự xưng khi người dùng yêu cầu, ví dụ "em", "mình".')
    tone: Tone | None = None
    answer_length: Length | None = None
    interests_add: list[str] = Field(default_factory=list, max_length=5)
    interests_remove: list[str] = Field(default_factory=list, max_length=5)
    evidence: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = Field(
        description='Trích NGUYÊN VĂN phần câu người dùng vừa gõ làm căn cứ.')


@dataclass
class UpdatePlan:
    applied: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)
    rejected: list[str] = field(default_factory=list)


def empty_profile() -> dict:
    return {'persona': None, 'occupation_text': None, 'address_user': None, 'address_self': None,
            'tone': None, 'answer_length': None, 'interests': [], 'pending': {}}


def _norm(text: str) -> str:
    return ' '.join(unicodedata.normalize('NFC', text).casefold().split())


def plan_update(current: dict, update: ProfileUpdate, *, user_message: str, categories: list[str]) -> UpdatePlan:
    out = UpdatePlan()
    if _norm(update.evidence) not in _norm(user_message):
        out.rejected.append('evidence_not_in_user_message')
        return out
    persona, occupation = update.persona, update.occupation_text
    if persona == 'khac' and not occupation:
        out.rejected.append('persona_khac_without_occupation')
        persona = None
    if occupation and persona is None:
        persona = 'khac'
    identity = {k: v for k, v in (('persona', persona), ('occupation_text', occupation)) if v is not None}
    if identity and any(current.get(k) != v for k, v in identity.items()):
        out.pending = identity
    for key in STYLE_FIELDS:
        value = getattr(update, key)
        if value is not None and current.get(key) != value:
            out.applied[key] = value
    known = {_norm(c): c for c in categories}
    interests = list(current.get('interests') or [])
    for name in update.interests_add + update.interests_remove:
        if _norm(name) not in known:
            out.rejected.append(f'unknown_category:{name}')
    removed = {known[_norm(n)] for n in update.interests_remove if _norm(n) in known}
    interests = [c for c in interests if c not in removed]
    for name in update.interests_add:
        cat = known.get(_norm(name))
        if cat and cat not in interests and cat not in removed:
            interests.append(cat)
    interests = interests[:10]
    if interests != list(current.get('interests') or []):
        out.applied['interests'] = interests
    return out


def style_instructions(profile: dict) -> str:
    """Đoạn hướng dẫn phong cách cho system prompt; rỗng khi chưa có hồ sơ."""
    lines = []
    if profile.get('persona'):
        label = profile.get('occupation_text') or PERSONA_LABELS.get(profile['persona'], profile['persona'])
        lines.append(f'Người dùng là {label}.')
        if profile['persona'] in PERSONA_FOCUS:
            lines.append(f'Trọng tâm: {PERSONA_FOCUS[profile["persona"]]}.')
    if profile.get('address_user'):
        lines.append(f'Gọi người dùng là "{profile["address_user"]}".')
    if profile.get('address_self'):
        lines.append(f'Tự xưng là "{profile["address_self"]}".')
    if profile.get('tone'):
        lines.append(f'Giọng văn: {TONE_LABELS[profile["tone"]]}.')
    if profile.get('answer_length'):
        lines.append(f'Độ dài câu trả lời: {LENGTH_LABELS[profile["answer_length"]]}.')
    if profile.get('interests'):
        lines.append('Chuyên mục quan tâm (dùng khi câu hỏi chung chung): ' + ', '.join(profile['interests']) + '.')
    if not lines:
        return ''
    return ('Hồ sơ người dùng (chỉ đổi cách trình bày và chọn tin khi hỏi chung chung; KHÔNG thêm sự thật, '
            'phân tích hay lời khuyên ngoài bằng chứng):\n' + '\n'.join('- ' + line for line in lines))


# ---------------------------------------------------------------------- Postgres
_COLS = ('persona', 'occupation_text', 'address_user', 'address_self', 'tone', 'answer_length', 'interests', 'pending')


def get_profile(conn, user_id: int) -> dict:
    row = conn.execute(f"SELECT {', '.join(_COLS)} FROM rag_user_profiles WHERE user_id = %s", (user_id,)).fetchone()
    if row is None:
        return empty_profile()
    prof = dict(zip(_COLS, row, strict=True))
    prof['interests'] = list(prof['interests'] or [])
    prof['pending'] = dict(prof['pending'] or {})
    return prof


def save_fields(conn, user_id: int, fields: dict, *, pending: dict | None = None, message_id: int | None = None):
    """Upsert các trường đã duyệt; `pending=None` giữ nguyên phần chờ xác nhận."""
    cols = [c for c in fields if c in _COLS and c != 'pending']
    values = [fields[c] for c in cols]
    if pending is not None:
        cols.append('pending')
        values.append(Jsonb(pending))
    if message_id is not None:
        cols.append('source_message_id')
        values.append(message_id)
    if not cols:
        return
    updates = ', '.join(f'{c} = EXCLUDED.{c}' for c in cols)
    conn.execute(
        f"INSERT INTO rag_user_profiles (user_id, {', '.join(cols)}) VALUES (%s, {', '.join(['%s'] * len(cols))}) "
        f"ON CONFLICT (user_id) DO UPDATE SET {updates}, updated_at = now()",
        (user_id, *values))


def apply_update(conn, user_id: int, update: ProfileUpdate, *, user_message: str, categories: list[str],
                 message_id: int | None = None) -> UpdatePlan:
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('rag_user_profiles'), %s::int)", (user_id % 2**31,))
        current = get_profile(conn, user_id)
        plan = plan_update(current, update, user_message=user_message, categories=categories)
        pending = {**plan.pending, 'message_id': message_id} if plan.pending else None
        if plan.applied or pending:
            save_fields(conn, user_id, plan.applied, pending=pending, message_id=message_id)
    return plan


def confirm_pending(conn, user_id: int, accept: bool) -> dict:
    with conn.transaction():
        current = get_profile(conn, user_id)
        chosen = {k: v for k, v in current['pending'].items() if k in IDENTITY_FIELDS} if accept else {}
        if chosen.get('persona') and chosen['persona'] != 'khac' and 'occupation_text' not in chosen:
            chosen['occupation_text'] = None
        save_fields(conn, user_id, chosen, pending={})
    return get_profile(conn, user_id)


def delete_profile(conn, user_id: int) -> None:
    conn.execute('DELETE FROM rag_user_profiles WHERE user_id = %s', (user_id,))
