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
import time
import html
import requests
from datetime import datetime, timedelta
from collections import defaultdict

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"

# 조회 기간: 오늘 기준 -14일 ~ +90일 (최근 공시 + 향후 예정 공시 폭넓게 커버)
# 필요하면 숫자를 더 늘려도 됩니다. DART API 자체 한도는 넉넉해서 문제 없습니다.
DAYS_BACK = 14
DAYS_FORWARD = 90

# report_nm(보고서명)에 아래 키워드가 포함되면 '실적' 또는 'IR' 관련 공시로 분류
EARNINGS_KEYWORDS = ["실적공시", "잠정실적", "결산실적"]
IR_KEYWORDS = ["기업설명회", "IR개최", "IR 개최"]

# 관심종목만 보고 싶으면 종목명을 여기 채우세요. 비워두면 전체.
# 예: WATCHLIST = ["SK하이닉스", "삼성전자", "한미반도체"]
WATCHLIST = []


def get_api_key():
    key = os.environ.get("DART_API_KEY")
    if not key:
        print("ERROR: 환경변수 DART_API_KEY가 설정되어 있지 않습니다.", file=sys.stderr)
        sys.exit(1)
    return key


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
    today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows_html = []

    for date_key in sorted(grouped.keys()):
        items = grouped[date_key]
        weekday = ["월", "화", "수", "목", "금", "토", "일"][
            datetime.strptime(date_key, "%Y%m%d").weekday()
        ]
        date_display = datetime.strptime(date_key, "%Y%m%d").strftime("%m.%d") + weekday

        item_links = []
        for it in items:
            corp = html.escape(it["corp_name"])
            tag = it["tag"]
            link = build_dart_link(it["rcept_no"])
            item_links.append(
                f'<a href="{link}" target="_blank" rel="noopener" data-corp="{corp}">{corp}'
                f'<span class="tag tag-{tag}">{tag}</span></a>'
            )

        rows_html.append(
            f'<div class="day-row" data-corps="{html.escape(",".join(it["corp_name"] for it in items))}">'
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
</style>
</head>
<body>
  <h1>실적 발표 일정 캘린더</h1>
  <div class="meta">총 {total_count}건 · 생성 {today_str} · 출처: DART(금융감독원 전자공시시스템)</div>
  <input id="search-box" class="search-box" type="text" placeholder="기업명 검색 (예: SK하이닉스, 삼성전자)">
  <div id="calendar">
  {"".join(rows_html) if rows_html else "<p>표시할 공시가 없습니다.</p>"}
  </div>
  <div id="empty-msg">검색 결과가 없습니다.</div>

  <script>
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


def main():
    api_key = get_api_key()
    today = datetime.now()
    bgn_de = (today - timedelta(days=DAYS_BACK)).strftime("%Y%m%d")
    end_de = (today + timedelta(days=DAYS_FORWARD)).strftime("%Y%m%d")

    print(f"조회 기간: {bgn_de} ~ {end_de}")
    raw_list = fetch_disclosures(api_key, bgn_de, end_de)
    print(f"전체 수신 공시 수: {len(raw_list)}")

    grouped = defaultdict(list)
    for item in raw_list:
        report_nm = item.get("report_nm", "")
        tag = classify(report_nm)
        if not tag:
            continue

        corp_name = item.get("corp_name", "")
        if WATCHLIST and corp_name not in WATCHLIST:
            continue

        grouped[item["rcept_dt"]].append(
            {
                "corp_name": corp_name,
                "tag": tag,
                "rcept_no": item.get("rcept_no", ""),
            }
        )

    matched_count = sum(len(v) for v in grouped.values())
    print(f"필터링 후 매칭 공시 수: {matched_count}")

    out_html = generate_html(grouped)

    out_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_html)

    print(f"완료: {out_path} 생성됨")


if __name__ == "__main__":
    main()
