# hwpx_chunker

한국어 **HWPX 규정·공문 문서**를 **조문(법규체) / 아웃라인 절(공문체)** 단위로 자동 청킹해 **구조화 JSON**으로 내보내는 파이프라인.
RAG·지식그래프 등 다운스트림이 바로 쓸 수 있도록, 문서 계층(장·절·조)·표·도형·메타(제정/개정일·수신/발신)를 청크에 함께 담는다.

> 본문·표·도형·**페이지 표시 순서**를 정확히 복원하기 위해, HWPX 렌더링에 Rust 엔진 **[rhwp](https://github.com/edwardkim/rhwp)** (MIT, © Edward Kim)를 사용한다. 자세한 사용법은 [`USAGE.md`](USAGE.md) 참고.

---

## 특징

- **문서 유형 자동 판별** — `법규체`(조문 체계) vs `공문체`(시달문/아웃라인)를 규칙으로 구분해 분기 청킹.
- **계층 보존** — `제1장 > 제3절 > 제5조`(법규체), 아웃라인 절(공문체) 경로를 청크에 부착.
- **표/도형 복원** — 표는 GFM 마크다운·HTML·XML 3형식, 도형(흐름도 등) 텍스트도 복원해 별도 필드로.
- **메타 추출** — 제정/개정일, 개정 이력, 수신·발신, 삭제 조문 여부 등.

## 요구 사항

| 항목 | 버전 |
|------|------|
| Python | ≥ 3.9 (표준 라이브러리만) |
| **rhwp 바이너리** | HWPX 렌더링용. `vendor/rhwp`에서 `cargo build --release` 로 빌드하거나 `RHWP_BIN` 환경변수로 경로 지정 |
| 입력 형식 | **`.HWPX`** (한글 2010 이상) |

## 빠른 시작

```bash
# 1) rhwp 빌드 (최초 1회)
cd vendor/rhwp && cargo build --release && cd ../..
# (또는)  export RHWP_BIN=/path/to/rhwp

# 2) 청킹 실행 — 디렉터리 / glob / 개별 파일
python main.py D:\regulations
python main.py "D:\regs\*.HWPX"
python main.py "D:\regs\규정A.HWPX" --verbose
# → output/ 에 결과 생성
```

## 출력 형식

```
output/
├── chunks.json          # 전체 청크 배열(모든 문서 합산)
├── stats.json           # 통계 요약(문서 수·unit별 분포·오류)
└── by_document/
    └── <doc_id>.json    # 문서별 청크 배열
```

각 청크는 다음 필드를 가진 dict (전체 레퍼런스: [`USAGE.md`](USAGE.md#청크-필드-레퍼런스)):

| 필드 | 설명 |
|------|------|
| `chunk_id` · `doc_id` | 고유 ID(`doc_id::article_label::split_index`) · 문서 ID |
| `doc_title` · `doc_type` | 문서 제목 · 규정 유형(`정관`/`규정`/`기준`/…/`기타`) |
| `doc_family` | **`법규체`** 또는 **`공문체`** |
| `unit` | 청크 단위 — 법규체: `연혁`/`조`/`부칙`, 공문체: `헤더`/`본문`/`붙임`/`목차` |
| `hierarchy_path` | 계층 경로(`제1장 > 제5조`) |
| `article_label` · `article_title` | 청크 레이블(`제5조`, `Ⅱ. 보증 절차`) · 제목 |
| `chapter_no/title` · `section_no/title` · `article_no` · `article_branch` | (법규체) 장·절·조·가지조문 |
| `recipient` · `sender` | (공문체) 수신처 · 발신명의 |
| `enacted` · `last_amended` · `amendment_dates` | 제정일 · 최종 개정일 · 개정일 목록 |
| `is_deleted` · `has_table` · `has_figure` · `has_appendix_ref` | 삭제 조문 · 표 · 도형 · 붙임/별표 참조 여부 |
| `split_index` · `split_total` · `char_len` | 분할 순번 · 전체 분할 수 · 글자 수 |
| `text` | 청크 본문 |
| `table_markdown` · `table_html` · `table_xml` | 표(3형식) |
| `figure_markdown` · `figure_html` · `figure_xml` | 도형(3형식) |

### `stats.json` 예시
```json
{ "n_documents": 5, "n_chunks_total": 245,
  "by_unit": { "연혁": 5, "조": 132, "부칙": 108 },
  "by_document": { "문서A": 37, "문서B": 23 } }
```

전체 설치·설정·문서유형 판별 로직·FAQ는 [`USAGE.md`](USAGE.md)에 있다.

## 라이선스 · 출처

- **이 프로젝트(hwpx_chunker) 코드: MIT** — [`LICENSE`](LICENSE) 참고.
- **HWPX 렌더링은 [rhwp](https://github.com/edwardkim/rhwp)(MIT, © Edward Kim) 소스를 사용한다.** `vendor/rhwp`에 포함된 원본 `LICENSE`·`THIRD_PARTY_LICENSES.md`를 그대로 유지한다(MIT 고지 의무).
- rhwp 의존 크레이트는 전부 허용적 라이선스(MIT/Apache-2.0/BSD/ISC/Zlib/Unicode)로, 카피레프트 없음.
