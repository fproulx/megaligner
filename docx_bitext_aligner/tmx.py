from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx_bitext_aligner import __version__
from docx_bitext_aligner.config import PairProcessingError, RunConfig
from docx_bitext_aligner.models import AlignmentUnit
from docx_bitext_aligner.utils import is_numericish_text, normalize_space

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
TMX_DOCTYPE = '<!DOCTYPE tmx SYSTEM "tmx14.dtd">'
TMX_CREATION_TOOL = "align-docx"


@dataclass(frozen=True)
class TmxWriteStats:
    input_units: int
    written_units: int
    duplicate_units: int = 0
    empty_units: int = 0
    normalized_units: int = 0
    trivial_numeric_units: int = 0


@dataclass(frozen=True)
class TmxWriteResult:
    stats: TmxWriteStats
    units: list[AlignmentUnit]


TMX_LEVEL1_SUBSET_DTD = """
<!ELEMENT tmx (header, body)>
<!ATTLIST tmx version CDATA #REQUIRED>
<!ELEMENT header (note | prop)*>
<!ATTLIST header
    creationtool CDATA #REQUIRED
    creationtoolversion CDATA #REQUIRED
    segtype CDATA #REQUIRED
    o-tmf CDATA #REQUIRED
    adminlang CDATA #REQUIRED
    srclang CDATA #REQUIRED
    datatype CDATA #REQUIRED
    creationdate CDATA #IMPLIED>
<!ELEMENT body (tu*)>
<!ELEMENT tu ((note | prop)*, tuv+)>
<!ATTLIST tu
    tuid CDATA #IMPLIED
    datatype CDATA #IMPLIED
    srclang CDATA #IMPLIED
    segtype CDATA #IMPLIED>
<!ELEMENT tuv ((note | prop)*, seg)>
<!ATTLIST tuv
    xml:lang CDATA #REQUIRED>
<!ELEMENT seg (#PCDATA)>
<!ELEMENT prop (#PCDATA)>
<!ATTLIST prop type CDATA #REQUIRED>
<!ELEMENT note (#PCDATA)>
"""


def add_prop(parent: Any, prop_type: str, value: str) -> None:
    from lxml import etree

    prop = etree.SubElement(parent, "prop", type=prop_type)
    prop.text = value


def normalized_alignment_unit(unit: AlignmentUnit) -> AlignmentUnit:
    # src_len/tgt_len are segment counts, not character spans, so whitespace
    # normalization does not invalidate the source/target segment references.
    src_text = normalize_space(unit.src_text)
    tgt_text = normalize_space(unit.tgt_text)
    if src_text == unit.src_text and tgt_text == unit.tgt_text:
        return unit
    return AlignmentUnit(
        src_start=unit.src_start,
        src_len=unit.src_len,
        tgt_start=unit.tgt_start,
        tgt_len=unit.tgt_len,
        similarity=unit.similarity,
        score=unit.score,
        src_text=src_text,
        tgt_text=tgt_text,
        tuid=unit.tuid,
    )


def is_trivial_numeric_unit(unit: AlignmentUnit) -> bool:
    return is_numericish_text(unit.src_text) and is_numericish_text(unit.tgt_text)


def prepare_tmx_units(
    units: list[AlignmentUnit],
    *,
    keep_trivial_numeric_units: bool = False,
) -> tuple[list[AlignmentUnit], TmxWriteStats]:
    prepared: list[AlignmentUnit] = []
    seen: dict[tuple[str, str], int] = {}
    duplicate_units = 0
    empty_units = 0
    normalized_units = 0
    trivial_numeric_units = 0

    for unit in units:
        normalized = normalized_alignment_unit(unit)
        if normalized.src_text != unit.src_text or normalized.tgt_text != unit.tgt_text:
            normalized_units += 1
        if not normalized.src_text or not normalized.tgt_text:
            empty_units += 1
            continue
        if not keep_trivial_numeric_units and is_trivial_numeric_unit(normalized):
            trivial_numeric_units += 1
            continue

        key = (normalized.src_text, normalized.tgt_text)
        existing_index = seen.get(key)
        if existing_index is not None:
            duplicate_units += 1
            if normalized.similarity > prepared[existing_index].similarity:
                prepared[existing_index] = normalized
            continue

        seen[key] = len(prepared)
        prepared.append(normalized)

    stats = TmxWriteStats(
        input_units=len(units),
        written_units=len(prepared),
        duplicate_units=duplicate_units,
        empty_units=empty_units,
        normalized_units=normalized_units,
        trivial_numeric_units=trivial_numeric_units,
    )
    return prepared, stats


def build_tmx_tree(units: list[AlignmentUnit], config: RunConfig) -> Any:
    from lxml import etree

    root = etree.Element("tmx", version="1.4")
    header = etree.SubElement(
        root,
        "header",
        creationtool=TMX_CREATION_TOOL,
        creationtoolversion=__version__,
        segtype="sentence",
        **{
            "o-tmf": "PlainText",
            "adminlang": config.src_lang,
            "srclang": config.src_lang,
            "datatype": "plaintext",
            "creationdate": config.creationdate,
        },
    )
    add_prop(header, "x-align-docx-model", config.model)
    if config.min_similarity is not None:
        add_prop(header, "x-align-docx-min-similarity", f"{config.min_similarity:.6f}")

    body = etree.SubElement(root, "body")
    for unit in units:
        tu = etree.SubElement(
            body,
            "tu",
            tuid=unit.tuid,
            datatype="plaintext",
            srclang=config.src_lang,
            segtype="sentence",
        )
        add_prop(tu, "x-align-docx-similarity", f"{unit.similarity:.6f}")
        add_prop(tu, "x-align-docx-grouping", f"{unit.src_len}:{unit.tgt_len}")

        src_tuv = etree.SubElement(tu, "tuv")
        src_tuv.set(XML_LANG, config.src_lang)
        src_seg = etree.SubElement(src_tuv, "seg")
        src_seg.text = unit.src_text

        tgt_tuv = etree.SubElement(tu, "tuv")
        tgt_tuv.set(XML_LANG, config.tgt_lang)
        tgt_seg = etree.SubElement(tgt_tuv, "seg")
        tgt_seg.text = unit.tgt_text

    return etree.ElementTree(root)


def validate_tmx_tree(tree: Any) -> None:
    from lxml import etree

    dtd = etree.DTD(StringIOCompat(TMX_LEVEL1_SUBSET_DTD))
    if not dtd.validate(tree):
        errors = "; ".join(str(error) for error in dtd.error_log.filter_from_errors())
        raise PairProcessingError(f"Generated TMX failed structural validation: {errors}")


def write_tmx(units: list[AlignmentUnit], out_path: Path, config: RunConfig) -> TmxWriteResult:
    prepared_units, stats = prepare_tmx_units(
        units,
        keep_trivial_numeric_units=config.keep_trivial_numeric_units,
    )
    if not prepared_units:
        raise PairProcessingError("TMX output has no usable translation units")

    tree = build_tmx_tree(prepared_units, config)
    validate_tmx_tree(tree)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(out_path.parent), prefix=f".{out_path.name}.") as temp_file:
        temp_path = Path(temp_file.name)
        tree.write(
            temp_file,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True,
            doctype=TMX_DOCTYPE,
        )
    temp_path.replace(out_path)
    parse_tmx_after_write(out_path)
    return TmxWriteResult(stats=stats, units=prepared_units)


def parse_tmx_after_write(path: Path) -> None:
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        etree.parse(str(path), parser=parser)
    except Exception as exc:
        raise PairProcessingError(f"TMX did not parse after writing: {path}") from exc


class StringIOCompat:
    def __init__(self, text: str) -> None:
        from io import StringIO

        self._buffer = StringIO(text)

    def read(self, *args: Any) -> str:
        return self._buffer.read(*args)
