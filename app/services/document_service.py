# app/services/document_service.py

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pypdf import PdfReader


from app.core.exceptions import DocumentProcessingError



SectionName = Literal[
    "summary", "experience", "education", "skills", "projects",
    "certifications", "other",
]


@dataclass
class DocumentChunk:
    """1 đơn vị nội dung sẽ đưa qua embedding_service rồi lưu vào ChromaDB."""
    chunk_id: str       # vd "experience_0" — dùng làm id trong Chroma collection
    section: SectionName
    content: str
    char_count: int = field(init=False)  # tự tính, không truyền tay

    def __post_init__(self) -> None:
        self.char_count = len(self.content)

SECTION_PATTERNS: dict[SectionName, str] = {
    "summary": r"^(professional\s+summary|summary|objective|about\s+me|tóm\s+tắt|giới\s+thiệu(?:\s+bản\s+thân)?)\s*:?\s*$",
    "experience": r"^(work\s+experience|experience|employment\s+history|kinh\s+nghiệm(?:\s+làm\s+việc)?)\s*:?\s*$",
    "education": r"^(education|academic\s+background|học\s+vấn|trình\s+độ\s+học\s+vấn)\s*:?\s*$",
    "skills": r"^(skills|technical\s+skills|kỹ\s+năng(?:\s+chuyên\s+môn)?)\s*:?\s*$",
    "projects": r"^(projects|personal\s+projects|dự\s+án(?:\s+cá\s+nhân)?)\s*:?\s*$",
    "certifications": r"^(certifications?|licenses?|chứng\s+chỉ)\s*:?\s*$",
}


def _find_section_headings(text: str) -> list[tuple[int, SectionName]]:
    """Quét từng dòng, trả về (line_index, section_name) cho dòng là heading.
    Heading thật thường NGẮN (<40 ký tự) và đứng riêng 1 dòng — nhờ vậy
    tránh false-positive khi từ "experience" xuất hiện giữa 1 câu dài.
    """
    lines = text.split("\n")
    headings: list[tuple[int, SectionName]] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > 40:
            continue
        for section, pattern in SECTION_PATTERNS.items():
            if re.match(pattern, stripped, flags=re.IGNORECASE):
                headings.append((idx, section))
                break
    return headings


def _slice_sections(
    text: str, headings: list[tuple[int, SectionName]]
) -> dict[SectionName, str]:
    """Dựa vào vị trí heading, cắt text thành dict {section: nội_dung}.
    Phần text TRƯỚC heading đầu tiên (tên, email, sđt...) được gộp vào "summary".
    """
    lines = text.split("\n")
    sections: dict[SectionName, list[str]] = {}
    if not headings:
        return {}

    first_idx = headings[0][0]
    preamble = "\n".join(lines[:first_idx]).strip()
    if preamble:
        sections.setdefault("summary", []).append(preamble)

    for i, (start_idx, section) in enumerate(headings):
        end_idx = headings[i + 1][0] if i + 1 < len(headings) else len(lines)
        content = "\n".join(lines[start_idx + 1 : end_idx]).strip()  # +1: bỏ dòng heading
        if content:
            sections.setdefault(section, []).append(content)

    return {sec: "\n".join(parts) for sec, parts in sections.items()}

def _split_fixed_size(
    text: str, section: SectionName, chunk_size: int, overlap: int, id_prefix: str,
) -> list[DocumentChunk]:
    """Chia text ~chunk_size ký tự, ưu tiên cắt tại ranh giới đoạn văn (\\n\\n)
    rồi mới đến câu (". "), tránh cắt giữa từ.
    `overlap`: số ký tự cuối của chunk trước được lặp lại ở đầu chunk sau,
    để không mất ngữ cảnh nếu 1 ý bị cắt ngay tại ranh giới 2 chunk.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(para) > chunk_size:
            # Đoạn văn tự nó đã dài hơn chunk_size -> tách tiếp theo câu
            for sent in re.split(r"(?<=[.!?])\s+", para):
                if len(current) + len(sent) + 1 <= chunk_size:
                    current = f"{current} {sent}".strip()
                else:
                    if current:
                        chunks.append(current)
                    current = (current[-overlap:] + " " + sent).strip() if overlap else sent
        else:
            if len(current) + len(para) + 1 <= chunk_size:
                current = f"{current}\n{para}".strip()
            else:
                if current:
                    chunks.append(current)
                current = (current[-overlap:] + "\n" + para).strip() if overlap else para

    if current:
        chunks.append(current)

    return [
        DocumentChunk(chunk_id=f"{id_prefix}_{i}", section=section, content=c)
        for i, c in enumerate(chunks)
    ]


def chunk_cv_text(text: str, chunk_size: int = 600, overlap: int = 100) -> list[DocumentChunk]:
    """Chiến lược hybrid:
    1. Thử nhận diện section chuẩn
    2. Nếu tìm được >=2 section -> chunk theo section; section nào dài quá
       chunk_size thì sub-chunk bên trong (vd Experience 10 năm kinh nghiệm)
    3. Không tìm được cấu trúc (CV format lạ/scan lỗi) -> fallback fixed-size
       trên toàn bộ text
    """
    headings = _find_section_headings(text)
    sections = _slice_sections(text, headings)

    # Ngưỡng >=2: nếu chỉ khớp 1 section, nhiều khả năng là false-positive
    # (vd chỉ có 1 dòng ngắn ngẫu nhiên trùng pattern "skills")
    if len(sections) >= 2:
        chunks: list[DocumentChunk] = []
        for section, content in sections.items():
            if len(content) <= chunk_size:
                chunks.append(DocumentChunk(chunk_id=f"{section}_0", section=section, content=content))
            else:
                chunks.extend(_split_fixed_size(content, section, chunk_size, overlap, id_prefix=section))
        return chunks

    return _split_fixed_size(text, "other", chunk_size, overlap, id_prefix="chunk")

def clean_text(text: str) -> str:
    """PDF extract ra text thường bị: từ ngắt giữa dòng do wrap, nhiều
    khoảng trắng/tab thừa, ligature lạ (fi, fl dính liền), nhiều dòng trống.
    """
    text = unicodedata.normalize("NFKC", text)          # chuẩn hoá ligature, ký tự full-width
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # nối từ bị gạch nối ngắt dòng: "develop-\nment" -> "development"
    text = re.sub(r"[ \t]+", " ", text)                    # gộp khoảng trắng/tab thừa
    text = re.sub(r"\n{3,}", "\n\n", text)                 # gộp 3+ dòng trống thành 2 (giữ ranh giới đoạn văn)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return text.strip()


def extract_text_from_pdf(file_path: str | Path) -> str:
    """Đọc toàn bộ text từ PDF, nối các trang bằng 2 dòng trống (giữ ranh giới trang)."""
    try:
        reader = PdfReader(str(file_path))
    except Exception as e:
        raise DocumentProcessingError(f"Không mở được file PDF: {e}") from e

    pages_text = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages_text)


def extract_text_from_txt(file_path: str | Path) -> str:
    """Đọc file .txt — thử utf-8 trước, fallback latin-1 nếu lỗi encoding."""
    path = Path(file_path)
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


class DocumentService:
    """Entry point duy nhất mà cv.py route sẽ gọi: file -> list[DocumentChunk]."""

    def __init__(self, chunk_size: int = 600, chunk_overlap: int = 100):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def process_file(self, file_path: str | Path) -> list[DocumentChunk]:
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix == ".pdf":
            raw_text = extract_text_from_pdf(path)
        elif suffix in {".txt", ".md"}:
            raw_text = extract_text_from_txt(path)
        else:
            raise DocumentProcessingError(f"Định dạng không hỗ trợ: {suffix}")

        cleaned = clean_text(raw_text)
        if not cleaned:
            raise DocumentProcessingError(
                "Không trích xuất được text — file có thể là ảnh scan, cần OCR."
            )

        return chunk_cv_text(cleaned, self.chunk_size, self.chunk_overlap)
    

