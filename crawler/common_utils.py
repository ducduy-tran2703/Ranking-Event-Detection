"""
Tiện ích dùng chung cho Silver Transformer của mọi nguồn báo.
"""

import hashlib
import re

# U+2028 (LINE SEPARATOR), U+2029 (PARAGRAPH SEPARATOR): hay lọt vào nội dung
#   dán từ trình soạn thảo WYSIWYG, không được các hàm xử lý text thông thường
#   (split theo "\n", regex anchor ^/$) nhận diện đúng như dòng mới thật.
# \xa0 (NON-BREAKING SPACE, sinh ra khi parse HTML entity &nbsp;): trông giống
#   khoảng trắng nhưng là ký tự khác, có thể gây lỗi tokenize cho NER/embedding.
_UNUSUAL_CHARS_RE = re.compile("[\u2028\u2029\xa0]")
_MULTI_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """
    Thay các ký tự bất thường (line/paragraph separator, nbsp) bằng khoảng trắng
    thường, đồng thời ép nhiều khoảng trắng liên tiếp thành 1 - cần thiết vì
    get_text(separator=" ", strip=True) có thể sinh khoảng trắng thừa khi nối
    các text node quanh thẻ inline (b, i, span...).
    """
    text = _UNUSUAL_CHARS_RE.sub(" ", text)
    text = _MULTI_WHITESPACE_RE.sub(" ", text)
    return text.strip()


def compute_article_id(url: str) -> str:
    """Sinh khóa chính ổn định cho 1 bài viết, dùng chung xuyên suốt các tầng."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()
