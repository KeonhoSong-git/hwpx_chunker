# hwpx_chunker

한국어 **HWPX 규정·공문 문서**를 **조문(법규체) / 아웃라인 절(공문체)** 단위로 자동 청킹해 **구조화 JSON**으로 내보내는 파이프라인.
RAG·지식그래프 등 다운스트림이 바로 쓸 수 있도록, 문서 계층(장·절·조)·표·도형·메타(제정/개정일·수신/발신)를 청크에 함께 담는다.

> **제작 배경**: 규정 하이브리드 RAG 프로젝트 **[Law-Manual-HybridRAG](https://github.com/KeonhoSong-git/Law-Manual-HybridRAG)** 를 만들면서, 원본 규정이 대부분 HWPX라 **이를 읽어 RAG 입력으로 쪼개는 단계**가 필요해 별도 도구로 분리·제작했다. (그 프로젝트는 이 청크 형식을 그대로 받아 KG·벡터를 만든다.)

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

## 입력

- **형식**: `.HWPX` (한글 2010 이상). `.hwp`(구버전)·`.pdf`는 미지원.
- **지정**: 디렉터리 · glob · 개별 파일 모두 가능.
  ```bash
  python main.py D:\regulations          # 폴더 안의 모든 .HWPX
  python main.py "D:\regs\*.HWPX"        # glob
  python main.py "D:\regs\감사규정.HWPX"   # 개별 파일
  ```
- 별도 전처리 불필요. 같은 폴더에 **규정(법규체)·공문(공문체)이 섞여 있어도** 문서별로 유형을 자동 판별해 분기 청킹한다.

## 출력

```
output/
├── chunks.json          # 전체 청크 배열(모든 문서 합산)
├── stats.json           # 통계 요약(문서 수·unit별 분포·오류)
└── by_document/
    └── <doc_id>.json    # 문서별 청크 배열
```

### 예시 ① 법규체(규정) — 연혁 청크 + 조문 청크

**입력 HWPX 본문(발췌)**
```
감사규정
  제 정 : 2010. 1. 1.
  개정(1) : 2016. 9. 30.
  개정(2) : 2023. 5. 1.

제1장 총칙
  제1조(목적) 이 규정은 내부감사의 기준과 절차를 정하여 감사 기능을 강화하고
            경영의 투명성을 높임을 목적으로 한다.
  제2조(정의) 이 규정에서 사용하는 용어의 뜻은 다음과 같다.
    1. "감사"란 업무 전반의 적정성을 점검·평가하는 활동을 말한다.
    2. "내부통제"란 ① 업무의 효율성 ② 재무보고의 신뢰성 ③ 법규 준수를
       합리적으로 보장하기 위한 절차를 말한다.
    3. "감사인"이란 감사 업무를 수행하는 임직원을 말한다.
```

→ 한 문서가 **연혁 1청크 + 조문 N청크**로 분리된다. 아래는 `by_document/감사규정.json` 의 두 원소.

**(1) 연혁 청크** — 제목 + 제·개정 이력
```json
{
  "chunk_id": "감사규정::연혁::0",
  "doc_id": "감사규정",
  "doc_title": "감사규정",
  "doc_type": "규정",
  "source_file": "감사규정.HWPX",
  "doc_family": "법규체",
  "unit": "연혁",
  "hierarchy_path": "연혁",
  "article_label": "연혁",
  "enacted": "2010. 1. 1.",
  "last_amended": "2023. 5. 1.",
  "amendment_dates": ["2010. 1. 1.", "2016. 9. 30.", "2023. 5. 1."],
  "split_index": 0,
  "split_total": 1,
  "char_len": 78,
  "text": "감사규정\n제 정 : 2010. 1. 1.\n개정(1) : 2016. 9. 30.\n개정(2) : 2023. 5. 1."
}
```

**(2) 조문 청크** — `제2조(정의)`, 항·호까지 본문에 포함
```json
{
  "chunk_id": "감사규정::제2조::0",
  "doc_id": "감사규정",
  "doc_title": "감사규정",
  "doc_type": "규정",
  "source_file": "감사규정.HWPX",
  "doc_family": "법규체",
  "unit": "조",
  "hierarchy_path": "제1장 총칙 > 제2조",
  "chapter_no": "1",
  "chapter_title": "총칙",
  "section_no": "",
  "section_title": "",
  "article_no": "2",
  "article_branch": "",
  "article_label": "제2조",
  "article_title": "정의",
  "enacted": "2010. 1. 1.",
  "last_amended": "2023. 5. 1.",
  "is_deleted": false,
  "has_table": false,
  "has_figure": false,
  "has_appendix_ref": false,
  "split_index": 0,
  "split_total": 1,
  "char_len": 196,
  "text": "제2조(정의) 이 규정에서 사용하는 용어의 뜻은 다음과 같다.\n1. \"감사\"란 업무 전반의 적정성을 점검·평가하는 활동을 말한다.\n2. \"내부통제\"란 ① 업무의 효율성 ② 재무보고의 신뢰성 ③ 법규 준수를 합리적으로 보장하기 위한 절차를 말한다.\n3. \"감사인\"이란 감사 업무를 수행하는 임직원을 말한다."
}
```

> 긴 조문은 `split_total`/`split_index`로 여러 청크로 나뉜다(예: `split_total: 3` → `…::제5조::0`, `…::제5조::1`, `…::제5조::2`).

### 예시 ② 공문체(업무지침) — 헤더 + 표 포함 본문 절

**입력 HWPX 본문(발췌)**
```
○○업무지침
  수신: 각 부점장        발신: 담당 이사
  시행: 2024. 1. 1.       문서번호: 총무-1234

1. 적용 대상
   가. 원화·외화 대출 및 보증
   나. 세부 구분은 다음 표에 따른다.
   | 구분 | 대상   | 한도  |
   | 원화 | 운전자금 | 10억 |
   | 외화 | 시설자금 | 5억  |
2. 처리 절차
   가. 신청 접수 후 5영업일 이내 심사한다.
```

**(1) 헤더 청크** — 수신·발신을 메타로 분리
```json
{
  "chunk_id": "○○업무지침::헤더::0",
  "doc_id": "○○업무지침",
  "doc_title": "○○업무지침",
  "doc_type": "기타",
  "source_file": "○○업무지침.HWPX",
  "doc_family": "공문체",
  "unit": "헤더",
  "hierarchy_path": "헤더",
  "article_label": "헤더",
  "recipient": "각 부점장",
  "sender": "담당 이사",
  "split_index": 0,
  "split_total": 1,
  "char_len": 96,
  "text": "○○업무지침\n수신: 각 부점장\n발신: 담당 이사\n시행: 2024. 1. 1.\n문서번호: 총무-1234"
}
```

**(2) 본문 절 청크** — 표는 본문에 인라인 + `table_*` 3형식으로도 제공
```json
{
  "chunk_id": "○○업무지침::1. 적용 대상::0",
  "doc_id": "○○업무지침",
  "doc_title": "○○업무지침",
  "doc_type": "기타",
  "doc_family": "공문체",
  "unit": "본문",
  "hierarchy_path": "1. 적용 대상",
  "article_label": "1. 적용 대상",
  "article_title": "1. 적용 대상",
  "recipient": "각 부점장",
  "sender": "담당 이사",
  "has_table": true,
  "has_figure": false,
  "split_index": 0,
  "split_total": 1,
  "char_len": 188,
  "text": "1. 적용 대상\n가. 원화·외화 대출 및 보증\n나. 세부 구분은 다음 표에 따른다.\n| 구분 | 대상 | 한도 |\n|---|---|---|\n| 원화 | 운전자금 | 10억 |\n| 외화 | 시설자금 | 5억 |",
  "table_markdown": "| 구분 | 대상 | 한도 |\n|---|---|---|\n| 원화 | 운전자금 | 10억 |\n| 외화 | 시설자금 | 5억 |",
  "table_html": "<table><tbody><tr><td>구분</td><td>대상</td><td>한도</td></tr><tr><td>원화</td><td>운전자금</td><td>10억</td></tr><tr><td>외화</td><td>시설자금</td><td>5억</td></tr></tbody></table>"
}
```

### 필드 레퍼런스(요약)
| 필드 | 설명 |
|------|------|
| `chunk_id` · `doc_id` | 고유 ID(`doc_id::article_label::split_index`) · 문서 ID |
| `doc_title` · `doc_type` | 제목 · 규정 유형(`정관`/`규정`/`기준`/…/`기타`) |
| `doc_family` | **`법규체`** 또는 **`공문체`** |
| `unit` | 법규체: `연혁`/`조`/`부칙` · 공문체: `헤더`/`본문`/`붙임`/`목차` |
| `hierarchy_path` · `article_label` · `article_title` | 계층 경로 · 청크 레이블 · 제목 |
| `chapter_*` · `section_*` · `article_no` · `article_branch` | (법규체) 장·절·조·가지조문 |
| `recipient` · `sender` | (공문체) 수신처 · 발신명의 |
| `enacted` · `last_amended` · `amendment_dates` | 제정일 · 최종 개정일 · 개정일 목록 |
| `is_deleted` · `has_table` · `has_figure` · `has_appendix_ref` | 삭제 조문 · 표 · 도형 · 붙임/별표 참조 |
| `split_index` · `split_total` · `char_len` | 분할 순번 · 전체 분할 수 · 글자 수 |
| `text` | 청크 본문 |
| `table_markdown` · `table_html` · `table_xml` · `figure_*` | 표·도형(각 3형식) |

> 전체 필드·`unit` 값 목록·문서유형 판별 로직·FAQ는 [`USAGE.md`](USAGE.md)에 있다.

### `stats.json` 예시
```json
{ "n_documents": 5, "n_chunks_total": 245,
  "by_unit": { "연혁": 5, "조": 132, "부칙": 108 },
  "by_document": { "감사규정": 37, "○○업무지침": 23 } }
```

## 라이선스 · 출처

- **이 프로젝트(hwpx_chunker) 코드: MIT** — [`LICENSE`](LICENSE) 참고.
- **HWPX 렌더링은 [rhwp](https://github.com/edwardkim/rhwp)(MIT, © Edward Kim) 소스를 사용한다.** `vendor/rhwp`에 포함된 원본 `LICENSE`·`THIRD_PARTY_LICENSES.md`를 그대로 유지한다(MIT 고지 의무).
- rhwp 의존 크레이트는 전부 허용적 라이선스(MIT/Apache-2.0/BSD/ISC/Zlib/Unicode)로, 카피레프트 없음.
