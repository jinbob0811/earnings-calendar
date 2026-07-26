#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DART Open API에서 '실적공시예고' / '기업설명회(IR)개최' 공시를 가져와
날짜별로 정리한 정적 HTML 캘린더(docs/index.html)를 생성합니다.

필요 환경변수:
  DART_API_KEY : opendart.fss.or.kr에서 발급받은 인증키 (40자리)

사용법:
  python scripts/fetch_earnings.py
"""

import os
import sys
import re
import io
import time
import html
import zipfile
import requests
from datetime import datetime, timedelta
from collections import defaultdict

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"

# 조회 기간: 오늘 기준 -45일 ~ +90일
# IR 개최 공시는 실제 행사보다 2~3주 전에 미리 접수되는 경우가 많아서,
# 접수일 기준 검색 범위를 넉넉히 잡아야 SK하이닉스/삼성전자 같은 대기업 IR도 놓치지 않습니다.
# (화면에 보여줄 때는 '실제 행사일' 기준으로 과거/미래를 나누므로, 검색 범위를 넓혀도
#  지난 일정이 다시 잔뜩 보이지는 않습니다)
DAYS_BACK = 45
DAYS_FORWARD = 90

# report_nm(보고서명)에 아래 키워드가 포함되면 '실적' 또는 'IR' 관련 공시로 분류
EARNINGS_KEYWORDS = ["실적공시", "잠정실적", "결산실적"]
IR_KEYWORDS = ["기업설명회", "IR개최", "IR 개최"]

# 관심종목만 보고 싶으면 종목명을 여기 채우세요. 비워두면 전체.
# 예: WATCHLIST = ["SK하이닉스", "삼성전자", "한미반도체"]
WATCHLIST = []

# 공시 원문에서 실제 개최/발표 예정일을 찾을 때 참고하는 키워드
# (구체적인 키워드를 먼저 확인하고, 못 찾으면 더 일반적인 키워드로 넘어간다)
EVENT_DATE_HINT_KEYWORDS = [
    "실적공시예정일",
    "결산실적공시예정일",
    "공시예정일",
    "개최일시",
    "개최 일시",
    "실시일시",
    "설명회일시",
    "발표일시",
    "개최일자",
]

DATE_PATTERNS = [
    re.compile(r"(20\d{2})\s*[.\-년]\s*(\d{1,2})\s*[.\-월]\s*(\d{1,2})\s*일?"),
]


def normalize_whitespace(text):
    """공시 원문은 표 정렬을 위해 글자 사이에 공백이 많이 들어가는 경우가 많다.
    (예: '공  시  예  정  일') 검색을 위해 연속 공백을 하나로 줄인다."""
    return re.sub(r"[ \t\u3000]+", " ", text)


def get_api_key():
    key = os.environ.get("DART_API_KEY")
    if not key:
        print("ERROR: 환경변수 DART_API_KEY가 설정되어 있지 않습니다.", file=sys.stderr)
        sys.exit(1)
    return key


def fetch_document_text(api_key, rcept_no):
    """공시 원문(zip 안의 xml/html)을 받아 순수 텍스트만 추출한다.
    실패하면 빈 문자열을 반환한다 (호출부에서 rcept_dt로 폴백)."""
    try:
        resp = requests.get(
            DART_DOCUMENT_URL,
            params={"crtfc_key": api_key, "rcept_no": rcept_no},
            timeout=15,
        )
        resp.raise_for_status()

        if b"PK" != resp.content[:2]:
            # zip이 아니면(에러 응답 등) 포기
            return ""

        text_parts = []
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for name in zf.namelist():
                raw = zf.read(name)
                for encoding in ("utf-8", "euc-kr", "cp949"):
                    try:
                        text_parts.append(raw.decode(encoding))
                        break
                    except UnicodeDecodeError:
                        continue

        full_text = "\n".join(text_parts)
        # 태그 제거해서 순수 텍스트만 남김
        full_text = re.sub(r"<[^>]+>", " ", full_text)
        return full_text
    except Exception:
        return ""


TIME_PATTERN = re.compile(r"(\d{1,2})\s*[:시]\s*(\d{2})")


def extract_event_date(text, fallback_dt):
    """문서 텍스트에서 실제 개최/발표 예정일(YYYYMMDD)과, 가능하면 시간(HH:MM)까지 추출한다.
    날짜를 못 찾으면 fallback_dt(공시 접수일)를 그대로 반환한다."""
    if not text:
        return fallback_dt, None, False

    text = normalize_whitespace(text)

    for keyword in EVENT_DATE_HINT_KEYWORDS:
        idx = text.find(keyword)
        if idx == -1:
            continue
        # 키워드 뒤쪽 200자 안에서 날짜/시간 패턴 탐색
        window = text[idx: idx + 200]
        for pattern in DATE_PATTERNS:
            m = pattern.search(window)
            if m:
                y, mo, d = m.groups()
                try:
                    dt = datetime(int(y), int(mo), int(d))
                except ValueError:
                    continue

                event_time = None
                # 날짜 패턴 바로 뒤쪽 30자 안에서 시간 패턴 탐색 (예: '14:00', '오후 2시')
                tail = window[m.end(): m.end() + 30]
                tm = TIME_PATTERN.search(tail)
                if tm:
                    hh, mm = int(tm.group(1)), int(tm.group(2))
                    if 0 <= hh <= 23 and 0 <= mm <= 59:
                        event_time = f"{hh:02d}:{mm:02d}"

                return dt.strftime("%Y%m%d"), event_time, True

    return fallback_dt, None, False


def fetch_disclosures(api_key, bgn_de, end_de):
    """DART list.json API를 페이지네이션하며 전체 결과를 가져온다."""
    results = []
    page_no = 1
    while True:
        params = {
            "crtfc_key": api_key,
            "bgn_de": bgn_de,
            "end_de": end_de,
            "pblntf_ty": "I",  # 거래소공시(수시공시) 카테고리
            "page_no": page_no,
            "page_count": 100,
        }
        resp = requests.get(DART_LIST_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status")
        if status == "013":  # 조회된 데이터 없음
            break
        if status != "000":
            print(f"WARNING: DART API status={status} message={data.get('message')}", file=sys.stderr)
            break

        page_list = data.get("list", [])
        results.extend(page_list)

        total_page = data.get("total_page", 1)
        if page_no >= total_page:
            break
        page_no += 1
        time.sleep(0.2)  # API 호출 과도 방지

    return results


def classify(report_nm):
    if any(k in report_nm for k in EARNINGS_KEYWORDS):
        return "예고"
    if any(k in report_nm for k in IR_KEYWORDS):
        return "IR"
    return None


def build_dart_link(rcept_no):
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def generate_html(grouped):
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d %H:%M")
    today_key = now.strftime("%Y%m%d")
    rows_html = []
    past_count = 0

    for date_key in sorted(grouped.keys()):
        items = grouped[date_key]
        weekday = ["월", "화", "수", "목", "금", "토", "일"][
            datetime.strptime(date_key, "%Y%m%d").weekday()
        ]
        date_display = datetime.strptime(date_key, "%Y%m%d").strftime("%m.%d") + weekday
        is_past = date_key < today_key
        row_class = "day-row past" if is_past else "day-row"
        if is_past:
            past_count += len(items)

        # 시간 미정(예고 등)은 먼저, IR처럼 시간이 있는 항목은 이른 시간 순으로 정렬
        items = sorted(items, key=lambda x: (1, x["event_time"]) if x.get("event_time") else (0, ""))

        item_links = []
        for it in items:
            corp = html.escape(it["corp_name"])
            tag = it["tag"]
            link = build_dart_link(it["rcept_no"])
            time_label = it.get("event_time") or "시간미정"
            item_links.append(
                f'<a href="{link}" target="_blank" rel="noopener" data-corp="{corp}">'
                f'<span class="time-label">{time_label}</span> {corp}'
                f'<span class="tag tag-{tag}">{tag}</span></a>'
            )

        rows_html.append(
            f'<div class="{row_class}" data-corps="{html.escape(",".join(it["corp_name"] for it in items))}">'
            f'<div class="day-label">{date_display}<span class="count">{len(items)}</span></div>'
            f'<div class="day-items">{"".join(item_links)}</div>'
            f'</div>'
        )

    total_count = sum(len(v) for v in grouped.values())

    html_doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>실적 발표 일정 캘린더</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    max-width: 760px;
    margin: 0 auto;
    padding: 24px 16px 60px;
    background: #0f1115;
    color: #e5e7eb;
  }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  .meta {{ color: #9ca3af; font-size: 13px; margin-bottom: 24px; }}
  .day-row {{
    display: flex;
    border-bottom: 1px solid #262a33;
    padding: 12px 0;
  }}
  .day-label {{
    flex: 0 0 70px;
    font-weight: 600;
    color: #93c5fd;
    font-size: 14px;
  }}
  .count {{
    display: inline-block;
    margin-left: 4px;
    font-size: 11px;
    color: #6b7280;
  }}
  .day-items {{ flex: 1; }}
  .day-items a {{
    display: inline-block;
    margin: 0 8px 8px 0;
    padding: 4px 8px;
    background: #1a1d24;
    border-radius: 6px;
    color: #e5e7eb;
    text-decoration: none;
    font-size: 13px;
  }}
  .day-items a:hover {{ background: #252a33; }}
  .tag {{
    font-size: 10px;
    margin-left: 4px;
    padding: 1px 4px;
    border-radius: 4px;
  }}
  .tag-예고 {{ background: #3730a3; color: #c7d2fe; }}
  .tag-IR {{ background: #065f46; color: #a7f3d0; }}
  .time-label {{
    display: inline-block;
    min-width: 42px;
    color: #6b7280;
    font-size: 11px;
    font-family: monospace;
  }}
  .search-box {{
    width: 100%;
    box-sizing: border-box;
    padding: 10px 14px;
    margin-bottom: 20px;
    background: #1a1d24;
    border: 1px solid #2b303b;
    border-radius: 8px;
    color: #e5e7eb;
    font-size: 14px;
  }}
  .search-box::placeholder {{ color: #6b7280; }}
  .day-row.hidden {{ display: none; }}
  .day-items a.hidden {{ display: none; }}
  #empty-msg {{ display: none; color: #9ca3af; padding: 20px 0; }}
  .day-row.past {{ display: none; }}
  .day-row.past.show-past {{ display: flex; opacity: 0.5; }}
  .past-toggle {{
    display: inline-block;
    margin-bottom: 16px;
    padding: 6px 12px;
    background: #1a1d24;
    border: 1px solid #2b303b;
    border-radius: 6px;
    color: #9ca3af;
    font-size: 12px;
    cursor: pointer;
  }}
  .past-toggle:hover {{ background: #22262f; }}
</style>
</head>
<body>
  <h1>실적 발표 일정 캘린더</h1>
  <div class="meta">총 {total_count}건 (다가오는 일정 {total_count - past_count}건) · 생성 {today_str} · 출처: DART(금융감독원 전자공시시스템)</div>
  <input id="search-box" class="search-box" type="text" placeholder="기업명 검색 (예: SK하이닉스, 삼성전자)">
  {f'<div id="past-toggle" class="past-toggle">지난 일정 {past_count}건 보기 ▾</div>' if past_count > 0 else ''}
  <div id="calendar">
  {"".join(rows_html) if rows_html else "<p>표시할 공시가 없습니다.</p>"}
  </div>
  <div id="empty-msg">검색 결과가 없습니다.</div>

  <script>
    const pastToggle = document.getElementById('past-toggle');
    if (pastToggle) {{
      let shown = false;
      pastToggle.addEventListener('click', () => {{
        shown = !shown;
        document.querySelectorAll('.day-row.past').forEach(row => {{
          row.classList.toggle('show-past', shown);
        }});
        pastToggle.textContent = shown
          ? pastToggle.textContent.replace('▾', '▴').replace('보기', '숨기기')
          : pastToggle.textContent.replace('▴', '▾').replace('숨기기', '보기');
      }});
    }}

    const searchBox = document.getElementById('search-box');
    const dayRows = Array.from(document.querySelectorAll('.day-row'));
    const emptyMsg = document.getElementById('empty-msg');

    searchBox.addEventListener('input', () => {{
      const q = searchBox.value.trim().toLowerCase();
      let visibleDays = 0;

      dayRows.forEach(row => {{
        const links = Array.from(row.querySelectorAll('.day-items a'));
        let visibleInRow = 0;

        links.forEach(a => {{
          const corp = (a.dataset.corp || '').toLowerCase();
          const match = q === '' || corp.includes(q);
          a.classList.toggle('hidden', !match);
          if (match) visibleInRow++;
        }});

        const rowMatch = visibleInRow > 0;
        row.classList.toggle('hidden', !rowMatch);
        if (rowMatch) visibleDays++;
      }});

      emptyMsg.style.display = (visibleDays === 0) ? 'block' : 'none';
    }});
  </script>
</body>
</html>
"""
    return html_doc


def build_date_chunks(bgn_de, end_de, max_days=88):
    """DART API는 corp_code 미지정 시 조회 기간이 3개월(약 90일)을 넘으면 안 되므로,
    전체 조회 기간을 max_days 이하의 여러 구간으로 쪼갠다."""
    start = datetime.strptime(bgn_de, "%Y%m%d")
    end = datetime.strptime(end_de, "%Y%m%d")

    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=max_days), end)
        chunks.append((cursor.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        cursor = chunk_end + timedelta(days=1)

    return chunks


def main():
    api_key = get_api_key()
    today = datetime.now()
    bgn_de = (today - timedelta(days=DAYS_BACK)).strftime("%Y%m%d")
    end_de = (today + timedelta(days=DAYS_FORWARD)).strftime("%Y%m%d")

    print(f"조회 기간: {bgn_de} ~ {end_de}")

    chunks = build_date_chunks(bgn_de, end_de)
    print(f"조회 구간 분할: {len(chunks)}개 ({chunks})")

    raw_list = []
    seen_rcept_no = set()
    for chunk_bgn, chunk_end in chunks:
        chunk_list = fetch_disclosures(api_key, chunk_bgn, chunk_end)
        for item in chunk_list:
            rcept_no = item.get("rcept_no")
            if rcept_no in seen_rcept_no:
                continue
            seen_rcept_no.add(rcept_no)
            raw_list.append(item)

    print(f"전체 수신 공시 수: {len(raw_list)}")

    matched_items = []
    for item in raw_list:
        report_nm = item.get("report_nm", "")
        tag = classify(report_nm)
        if not tag:
            continue

        corp_name = item.get("corp_name", "")
        if WATCHLIST and corp_name not in WATCHLIST:
            continue

        matched_items.append(
            {
                "corp_name": corp_name,
                "tag": tag,
                "rcept_no": item.get("rcept_no", ""),
                "rcept_dt": item.get("rcept_dt", ""),
            }
        )

    print(f"필터링 후 매칭 공시 수: {len(matched_items)}")
    print("공시 원문에서 실제 개최/발표일 추출 중...")

    today_key = today.strftime("%Y%m%d")
    grouped = defaultdict(list)
    extracted_ok = 0
    future_count = 0
    tag_stats = defaultdict(lambda: {"total": 0, "found": 0, "future": 0})

    for i, it in enumerate(matched_items):
        text = fetch_document_text(api_key, it["rcept_no"])
        event_date, event_time, found = extract_event_date(text, it["rcept_dt"])
        if found:
            extracted_ok += 1
        is_future = event_date > today_key
        if is_future:
            future_count += 1
        time.sleep(0.15)  # API 호출 과도 방지

        tag_stats[it["tag"]]["total"] += 1
        if found:
            tag_stats[it["tag"]]["found"] += 1
        if is_future:
            tag_stats[it["tag"]]["future"] += 1

        # 디버그: IR 태그 항목 중 처음 5건은 실제로 받아온 텍스트 길이/내용 일부를 로그에 남긴다
        if it["tag"] == "IR" and tag_stats["IR"]["total"] <= 5:
            snippet = normalize_whitespace(text)[:300].replace("\n", " ") if text else "(빈 텍스트 - 문서를 못 받아왔음)"
            print(f"  [IR 디버그] {it['corp_name']} rcept_no={it['rcept_no']} text_len={len(text)}")
            print(f"    내용 일부: {snippet}")

        # 디버그: 처음 30건은 회사명/태그 -> 추출된 날짜/시간을 그대로 로그에 남긴다
        if i < 30:
            marker = "O" if found else "x"
            future_marker = "(미래)" if is_future else "(과거/오늘)"
            time_display = event_time or "-"
            print(f"  [{marker}][{it['tag']}] {it['corp_name']} | rcept_dt={it['rcept_dt']} -> event_date={event_date} {time_display} {future_marker}")

        grouped[event_date].append(
            {
                "corp_name": it["corp_name"],
                "tag": it["tag"],
                "rcept_no": it["rcept_no"],
                "event_time": event_time,
            }
        )

    print(f"원문에서 실제 날짜 추출 성공: {extracted_ok}/{len(matched_items)}건 (나머지는 공시 접수일로 대체)")
    print(f"추출된 날짜가 오늘보다 미래인 건수: {future_count}/{len(matched_items)}건")
    for tag_name, stats in tag_stats.items():
        print(f"  태그별 통계 [{tag_name}]: 전체 {stats['total']}건 / 날짜추출성공 {stats['found']}건 / 미래 {stats['future']}건")

    out_html = generate_html(grouped)

    out_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_html)

    print(f"완료: {out_path} 생성됨")


if __name__ == "__main__":
    main()
