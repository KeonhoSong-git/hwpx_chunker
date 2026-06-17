# -*- coding: utf-8 -*-
"""OCR(비전) ↔ 청커 추출 비교 하네스.

목적:
    rhwp 마크다운 백엔드로 뽑은 청크 텍스트가 '문서에 실제로 보이는 내용'과
    일치하는지 검증한다. 원문 HWPX → (rhwp export-svg) → (Edge headless
    print-to-pdf) 로 페이지를 PDF로 래스터화해, 사람/Claude 비전이 OCR한
    결과와 청커 출력을 같은 폴더에 모아 페이지 단위로 대조한다.

    rhwp 의 export-png 는 native-skia feature(+MSVC 링커) 가 필요해 환경에
    따라 빌드가 어렵다. 대신 어디서나 되는 export-svg 로 페이지 SVG(폰트
    임베드)를 만든 뒤, Windows 기본 탑재 Edge(Chromium) 헤드리스로 PDF 렌더한다.

사용:
    python tools/ocr_compare.py <HWPX경로> [--pages 0,7,12] [--out 폴더]
    --pages 생략 시 전체 페이지.

산출(기본 _compare/<doc_stem>/):
    pNNN.pdf        Edge 렌더 PDF (1-based 페이지번호) — 비전 OCR 대상
    extract.json    rhwp_markdown_by_page  +  chunks[{unit,label,split,text}]
    README.txt      대조 절차
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from regchunker.config import RHWP_BIN  # noqa: E402
from regchunker.hwpx_reader import _export_markdown_pages, read_paragraphs  # noqa: E402
from regchunker.router import route_document  # noqa: E402
from regchunker import parse_document, parse_outline_document  # noqa: E402

_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
_RE_SVG_PAGE = re.compile(r"_(\d+)\.svg$", re.I)


def _find_edge():
    for p in _EDGE_CANDIDATES:
        if os.path.isfile(p):
            return p
    raise FileNotFoundError("Edge(msedge.exe)를 찾을 수 없습니다.")


def _export_svgs(path: str, svg_dir: str):
    """rhwp export-svg --embed-fonts → {page_num(1-based): svg경로}."""
    os.makedirs(svg_dir, exist_ok=True)
    r = subprocess.run(
        [RHWP_BIN, "export-svg", path, "-o", svg_dir, "--embed-fonts"],
        capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("export-svg 실패: "
                           + r.stderr.decode("utf-8", "replace")[:300])
    out = {}
    for fp in glob.glob(os.path.join(svg_dir, "*.svg")):
        m = _RE_SVG_PAGE.search(os.path.basename(fp))
        out[int(m.group(1)) if m else 1] = fp
    return out


def _svg_to_pdf(edge: str, svg_path: str, pdf_path: str) -> bool:
    """Edge 헤드리스로 SVG→PDF. 기본 프로파일(--user-data-dir 미지정)이
    가장 안정적이며, 빈 임시 프로파일은 첫실행 설정이 print-to-pdf를 막는다.
    Edge 런처는 렌더 자식보다 먼저 종료하므로 파일 생성을 폴링한다."""
    # 드라이브 콜론(C:)은 인코딩하면 Chromium이 거부 → safe=":/".
    uri = "file:///" + urllib.parse.quote(
        os.path.abspath(svg_path).replace("\\", "/"), safe=":/")
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    subprocess.run(
        [edge, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf_path}", uri],
        capture_output=True, timeout=180)
    for _ in range(80):           # 비동기 기록 대기(최대 20초)
        if os.path.isfile(pdf_path) and os.path.getsize(pdf_path) > 0:
            return True
        time.sleep(0.25)
    return os.path.isfile(pdf_path)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("hwpx")
    ap.add_argument("--pages", default=None,
                    help="1-based 페이지 콤마목록 (예: 1,8,13). 생략 시 전체")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    path = args.hwpx
    stem = os.path.splitext(os.path.basename(path))[0]
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = args.out or os.path.join(repo, "_compare", stem[:60])
    os.makedirs(out_dir, exist_ok=True)

    want = None
    if args.pages:
        want = {int(x) for x in args.pages.split(",") if x.strip()}

    # 1) rhwp 마크다운(청커가 보는 텍스트)
    md_pages = {pg: md for pg, md in _export_markdown_pages(path)}

    # 2) 청커 출력
    paras = read_paragraphs(path)
    family = route_document(os.path.basename(path), paras)
    chunks = (parse_outline_document(paras, os.path.basename(path))
              if family == "공문체"
              else parse_document(paras, os.path.basename(path)))
    chunk_dump = [{"unit": c.unit, "label": c.article_label,
                   "split": f"{c.split_index}/{c.split_total}",
                   "char_len": c.char_len, "text": c.text}
                  for c in chunks]

    # 3) SVG → PDF 렌더
    edge = _find_edge()
    svg_dir = os.path.join(out_dir, "_svg")
    svgs = _export_svgs(path, svg_dir)
    n_pdf = 0
    for pg in sorted(svgs):
        if want is not None and pg not in want:
            continue
        pdf = os.path.join(out_dir, f"p{pg:03d}.pdf")
        if _svg_to_pdf(edge, svgs[pg], pdf):
            n_pdf += 1
        else:
            print(f"[pdf 실패 p{pg}]")

    with open(os.path.join(out_dir, "extract.json"), "w", encoding="utf-8") as f:
        json.dump({"source": os.path.basename(path), "family": family,
                   "n_pages": len(md_pages), "n_chunks": len(chunks),
                   "rhwp_markdown_by_page": md_pages, "chunks": chunk_dump},
                  f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "README.txt"), "w", encoding="utf-8") as f:
        f.write("대조 절차\n"
                "1) pNNN.pdf 를 비전으로 읽어 실제 문서 텍스트 확인\n"
                "2) extract.json.rhwp_markdown_by_page[페이지] 와 비교\n"
                "3) chunks[] 에서 누락·왜곡·순서오류 확인\n")

    print(f"family={family}  pages={len(md_pages)}  chunks={len(chunks)}  pdf={n_pdf}")
    print(f"out → {out_dir}")


if __name__ == "__main__":
    main(sys.argv[1:])
