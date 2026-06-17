# -*- coding: utf-8 -*-
"""HWPX 규정 문서 → 조문 단위 청크(JSON) 변환 진입점.

사용:
    python main.py                         # config의 기본 입력 폴더/패턴 사용
    python main.py <입력폴더>              # 입력 폴더 지정
    python main.py <파일1.HWPX> ...        # 개별 파일 지정
    python main.py --verbose <폴더>        # 상세 로그 출력

환경변수로 경로/파라미터 재정의 가능 (regchunker/config.py 참고):
    HWPX_INPUT_DIR, HWPX_INPUT_GLOB, HWPX_OUTPUT_DIR, HWPX_MAX_CHARS, HWPX_MIN_CHARS

출력(output/):
    chunks.json              전체 청크 1개 배열
    by_document/<doc>.json   문서별 청크 (표 포함 청크에 table_markdown/table_html 필드 포함)
    stats.json               문서·단위별 통계 + 오류 파일 목록
"""
import glob
import json
import logging
import os
import sys
from collections import Counter
from typing import List, Tuple  # Tuple: resolve_inputs 반환 타입에 사용

from regchunker import (
    read_paragraphs, parse_document, parse_outline_document,
    route_document, Chunk,
)
from regchunker.config import DEFAULT_INPUT_DIR, INPUT_GLOB, OUTPUT_DIR
from regchunker.normalize import scrub

# 출력 직전 정리 대상 문자열 필드 (객체대체문자 ￼·PUA 등 잡음 글리프 제거)
_SCRUB_FIELDS = (
    "text", "doc_title", "article_title", "chapter_title", "section_title",
    "hierarchy_path", "article_label", "recipient", "sender", "enacted", "last_amended",
    "table_markdown", "table_html", "figure_markdown", "figure_html",
)


def _scrub_chunk(d: dict) -> dict:
    for k in _SCRUB_FIELDS:
        v = d.get(k)
        if isinstance(v, str):
            d[k] = scrub(v)
        elif isinstance(v, list):
            d[k] = [scrub(x) if isinstance(x, str) else x for x in v]
    return d

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stdout,
    )


def resolve_inputs(argv: List[str]) -> Tuple[List[str], bool]:
    """CLI 인자 → (처리할 HWPX 경로 목록, verbose 플래그)."""
    verbose = "--verbose" in argv or "-v" in argv
    args = [a for a in argv if a not in ("--verbose", "-v")]

    if not args:
        return sorted(glob.glob(os.path.join(DEFAULT_INPUT_DIR, INPUT_GLOB))), verbose

    files: List[str] = []
    for a in args:
        if os.path.isdir(a):
            files.extend(sorted(glob.glob(os.path.join(a, INPUT_GLOB))))
        elif os.path.isfile(a):
            files.append(a)
        else:
            files.extend(sorted(glob.glob(a)))
    return files, verbose


def write_json(path: str, obj: object) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def main(argv: List[str]) -> int:
    inputs, verbose = resolve_inputs(argv)
    _setup_logging(verbose)

    if not inputs:
        logger.error("[!] 입력 파일을 찾지 못했습니다. (폴더=%s, 패턴=%s)", DEFAULT_INPUT_DIR, INPUT_GLOB)
        return 1

    by_doc_dir = os.path.join(OUTPUT_DIR, "by_document")
    os.makedirs(by_doc_dir, exist_ok=True)

    all_chunks: List[dict] = []
    per_doc_counts: Counter = Counter()
    per_unit_counts: Counter = Counter()
    doc_summaries: List[dict] = []
    errors: List[dict] = []

    for path in inputs:
        fname = os.path.basename(path)
        try:
            paras = read_paragraphs(path)
            logger.debug("[DEBUG] %s  단락=%d", fname, len(paras))
            family = route_document(fname, paras)
            if family == "공문체":
                chunks: List[Chunk] = parse_outline_document(paras, fname)
            else:
                chunks = parse_document(paras, fname)
        except Exception as exc:
            logger.error("[ERR] %s: %s", fname, exc)
            errors.append({"source_file": fname, "error": str(exc)})
            continue

        dicts = [_scrub_chunk(c.to_dict()) for c in chunks]
        doc_id = chunks[0].doc_id if chunks else fname
        doc_title = scrub(chunks[0].doc_title) if chunks else fname
        unit_counter: Counter = Counter(c.unit for c in chunks)
        n_tables = sum(1 for c in chunks if c.has_table)

        write_json(os.path.join(by_doc_dir, f"{doc_id}.json"), dicts)
        all_chunks.extend(dicts)
        per_doc_counts[doc_id] = len(dicts)
        for u, n in unit_counter.items():
            per_unit_counts[u] += n

        doc_summaries.append({
            "doc_id": doc_id,
            "doc_title": doc_title,
            "doc_type": chunks[0].doc_type if chunks else "",
            "doc_family": family,
            "source_file": fname,
            "n_chunks": len(dicts),
            "n_table_chunks": n_tables,
            "units": dict(unit_counter),
            "n_deleted": sum(1 for c in chunks if c.is_deleted),
            "n_figure": sum(1 for c in chunks if c.has_figure),
            "n_oversized_split": sum(1 for c in chunks if c.split_total > 1),
        })
        logger.info("[OK] %s | %s  단락=%d  청크=%d  표청크=%d  %s",
                    family, fname[:40], len(paras), len(dicts), n_tables, dict(unit_counter))

    write_json(os.path.join(OUTPUT_DIR, "chunks.json"), all_chunks)
    n_table_chunks_total = sum(d.get("n_table_chunks", 0) for d in doc_summaries)
    write_json(os.path.join(OUTPUT_DIR, "stats.json"), {
        "n_documents": len(inputs),
        "n_ok": len(inputs) - len(errors),
        "n_errors": len(errors),
        "n_chunks_total": len(all_chunks),
        "n_table_chunks_total": n_table_chunks_total,
        "by_unit": dict(per_unit_counts),
        "by_document": dict(per_doc_counts),
        "documents": doc_summaries,
        "errors": errors,
    })

    logger.info("\n총 문서=%d  성공=%d  오류=%d", len(inputs), len(inputs) - len(errors), len(errors))
    logger.info("총 청크=%d  표포함청크=%d  단위별=%s", len(all_chunks), n_table_chunks_total, dict(per_unit_counts))
    logger.info("출력 → %s", OUTPUT_DIR)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
