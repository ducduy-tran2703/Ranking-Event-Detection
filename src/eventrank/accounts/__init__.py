"""Tài khoản người dùng (migration 003–006): đăng ký, đăng nhập bằng phiên lưu DB, token email, "của tôi", quản trị.

Chỉ chứa nghiệp vụ trên một kết nối psycopg (autocommit); FastAPI gói lại ở `apps/api/accounts.py`.
Hợp đồng JSON khớp lớp giả lập của web (`apps/web/src/api/{auth,me,admin}.ts`) để web chỉ cần `VITE_AUTH_MOCK=0`.

    uv run python -m eventrank.accounts create-user --email a@b.vn --name "Quản trị" --role admin
    uv run python -m eventrank.accounts cleanup      # dọn dữ liệu cá nhân quá hạn lưu
"""
