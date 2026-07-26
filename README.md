# 실적 발표 일정 캘린더 (개인용)

DART Open API에서 '실적공시예고' / '기업설명회(IR)개최' 공시를 매일 자동으로 가져와
정적 웹페이지로 보여주는 개인용 대시보드입니다. GitHub Pages + GitHub Actions로
서버 없이 무료로 매일 자동 갱신됩니다.

## 설치 순서 (최초 1회)

1. **이 폴더 전체를 GitHub 저장소에 업로드**
   - GitHub에서 새 저장소 생성 (예: `earnings-calendar`, Public)
   - 이 폴더 안의 파일/폴더 구조를 그대로 올리기
     (`.github/`, `docs/`, `scripts/`, `requirements.txt`, `README.md`)

2. **저장소에 DART 인증키 등록**
   - 저장소 → Settings → Secrets and variables → Actions → New repository secret
   - Name: `DART_API_KEY`
   - Value: 발급받은 40자리 인증키 붙여넣기

3. **GitHub Pages 활성화**
   - 저장소 → Settings → Pages
   - Source: `Deploy from a branch`
   - Branch: `main` / 폴더: `/docs` 선택 → Save
   - 몇 분 뒤 `https://<사용자명>.github.io/<저장소명>/` 로 접속 가능

4. **첫 실행 (수동)**
   - 저장소 → Actions 탭 → "Update Earnings Calendar" 워크플로우 선택
   - 우측 "Run workflow" 버튼 클릭 → 실행
   - 완료되면 `docs/index.html`이 자동으로 갱신되고 Pages에 반영됨

이후에는 **평일 매일 한국시간 오전 8시**에 자동으로 갱신됩니다.
(`.github/workflows/update.yml` 상단의 cron 값을 수정하면 시간을 바꿀 수 있어요.)

## 관심종목만 보고 싶다면

`scripts/fetch_earnings.py` 상단의 `WATCHLIST` 리스트에 종목명을 채워 넣으세요.

```python
WATCHLIST = ["SK하이닉스", "삼성전자", "한미반도체"]
```

비워두면(`[]`) 전체 종목이 표시됩니다.

## 참고 / 한계

- 표시되는 날짜는 **DART 공시 접수일(rcept_dt)** 기준입니다. '실적공시예고' 공시는
  통상 실제 발표일보다 며칠~수주 전에 접수되므로, 정확한 발표 일시는 각 항목의
  링크를 눌러 DART 원문 공시에서 확인하는 것을 권장합니다.
- 조회 기간은 기본적으로 오늘 기준 -7일 ~ +30일입니다. `fetch_earnings.py`의
  `DAYS_BACK`, `DAYS_FORWARD` 값을 조정할 수 있습니다.
- DART Open API 무료 호출 한도가 있으니(1일 20,000회 수준), 매일 1회 자동 실행은
  전혀 문제 없는 수준입니다.

## 로컬에서 직접 실행해보고 싶다면

```bash
pip install -r requirements.txt
export DART_API_KEY="발급받은키"
python scripts/fetch_earnings.py
open docs/index.html   # 또는 브라우저로 직접 열기
```
