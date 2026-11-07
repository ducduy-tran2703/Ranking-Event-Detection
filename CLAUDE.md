@AGENTS.md

# Riêng cho Claude Code

- Skill của dự án nằm trong `.claude/skills/` — dùng khi đúng tình huống:
  - `tdd` — viết test trước khi sửa code, test parser bằng HTML mẫu
  - `add-news-source` — thêm một báo mới vào crawler
  - `data-lake` — mọi thao tác đọc/ghi bucket R2
  - `eval-protocol` — đánh giá gom cụm, đặt tên, xu hướng
- Quyền chung của nhóm ở `.claude/settings.json` (có commit). Quyền cá nhân để trong `.claude/settings.local.json` (không commit).
