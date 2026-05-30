"""语义分块：按段落切分后，合并短段落、拆分长段落"""

import re
from config import get_settings

settings = get_settings()


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数：中文 1 字 ≈ 1 token，英文 1 词 ≈ 1.3 token"""
    chinese_chars = len(re.findall(r'[一-鿿]', text))
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    return chinese_chars + int(english_words * 1.3)


def split_by_paragraphs(text: str) -> list[str]:
    """按段落切分：空行或 Markdown 标题作为分界"""
    blocks = re.split(r'\n(?=#{1,6}\s)|\n{2,}', text)
    return [b.strip() for b in blocks if b.strip()]


def chunk_text(text: str) -> list[dict]:
    """
    语义分块：按段落切分后，合并短段落、拆分长段落。
    确保每块在 chunk_min ~ chunk_max token 之间，相邻块有 overlap。
    """
    paragraphs = split_by_paragraphs(text)
    chunks = []
    current_chunk = ""
    chunk_index = 0

    for para in paragraphs:
        candidate = current_chunk + "\n" + para if current_chunk else para

        if estimate_tokens(candidate) <= settings.chunk_max_tokens:
            current_chunk = candidate
        else:
            if current_chunk:
                chunks.append({
                    "content": current_chunk.strip(),
                    "chunk_index": chunk_index,
                })
                chunk_index += 1

                if settings.chunk_overlap_ratio > 0:
                    overlap_len = int(len(current_chunk) * settings.chunk_overlap_ratio)
                    current_chunk = current_chunk[-overlap_len:] + "\n" + para
                else:
                    current_chunk = para
            else:
                current_chunk = para

    if current_chunk:
        chunks.append({
            "content": current_chunk.strip(),
            "chunk_index": chunk_index,
        })

    # 合并太短的 chunk 到相邻块
    merged = []
    for c in chunks:
        if estimate_tokens(c['content']) < settings.chunk_min_tokens and merged:
            merged[-1]['content'] += "\n" + c['content']
        else:
            c['chunk_index'] = len(merged)
            merged.append(c)

    return merged
