from __future__ import annotations

import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

from docx_bitext_aligner.models import Segment
from docx_bitext_aligner.utils import normalize_space


def iter_block_items(parent: Any) -> Iterable[Any]:
    from docx.document import Document as DocumentObject
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    if isinstance(parent, DocumentObject):
        parent_elm = parent.element.body
    else:
        parent_elm = parent._tc

    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def iter_table_paragraphs(table: Any) -> Iterable[str]:
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for row in table.rows:
        for cell in row.cells:
            for block in iter_block_items(cell):
                if isinstance(block, Paragraph):
                    yield block.text
                elif isinstance(block, Table):
                    yield from iter_table_paragraphs(block)


def extract_docx_paragraphs(path: Path) -> list[str]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    paragraphs: list[str] = []
    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = normalize_space(block.text)
            if text:
                paragraphs.append(text)
        elif isinstance(block, Table):
            for text in iter_table_paragraphs(block):
                cleaned = normalize_space(text)
                if cleaned:
                    paragraphs.append(cleaned)
    return paragraphs


@lru_cache(maxsize=None)
def get_pysbd_segmenter(lang_base: str) -> Any:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r".*invalid escape sequence.*", category=SyntaxWarning)
        import pysbd

    return pysbd.Segmenter(language=lang_base, clean=False)


@lru_cache(maxsize=1)
def get_razdel_sentenize() -> Callable[[str], Any]:
    from razdel import sentenize

    return sentenize


def split_sentences(paragraph: str, lang: str) -> list[str]:
    lang_base = lang.lower().split("-")[0].split("_")[0]
    if lang_base == "ru":
        sentenize = get_razdel_sentenize()
        return [normalize_space(match.text) for match in sentenize(paragraph) if normalize_space(match.text)]

    segmenter = get_pysbd_segmenter(lang_base)
    return [normalize_space(sentence) for sentence in segmenter.segment(paragraph) if normalize_space(sentence)]


def segment_paragraphs(paragraphs: list[str], lang: str) -> list[Segment]:
    segments: list[Segment] = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        for sentence_index, sentence in enumerate(split_sentences(paragraph, lang)):
            segments.append(
                Segment(
                    text=sentence,
                    paragraph_index=paragraph_index,
                    sentence_index=sentence_index,
                    global_index=len(segments),
                )
            )
    return segments
