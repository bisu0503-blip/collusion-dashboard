# 담합 의심 실시간 대시보드

KOSIS OpenAPI에서 국내 밀가루/설탕/식용유 가격지수를 가져오고, FAO 공식 Food Price Index 페이지에서 최신 월별 국제 식량가격 CSV와 원/달러 환율을 수집해 담합 의심 점수를 계산하는 Streamlit 웹앱입니다.

이 앱은 법적 의미의 담합 판정 도구가 아니라, 조사 우선순위를 정하기 위한 위험 신호 대시보드입니다.

## 데이터 수집 방식

CSV 파일을 저장소에 포함하지 않습니다.

- 국내 밀가루/설탕/식용유: KOSIS OpenAPI
- 국제 곡물/설탕/식물성유지: FAO Food Price Index 공식 월별 CSV
- 원/달러 환율: FRED DEXKOUS 일별 CSV를 월평균으로 변환

FAO 공식 페이지:

```text
https://www.fao.org/worldfoodsituation/foodpricesindex/en/
```

앱은 위 페이지에서 `food_price_indices_data.csv` 링크를 자동으로 찾아 다운로드합니다. `FAO_CSV_URL`을 직접 지정하면 그 URL을 우선 사용합니다.

환율은 기본적으로 아래 CSV를 사용합니다.

```text
https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXKOUS
```

앱은 일별 원/달러 환율을 월평균으로 바꾼 뒤 `FAO 지수 × 환율지수 / 100` 방식으로 원화 기준 국제 원가지수를 계산합니다.

## 필요한 Secrets

Streamlit Community Cloud의 `App settings > Secrets`에 아래 형식으로 입력합니다.

```toml
KOSIS_API_KEY = "발급받은_KOSIS_API_키"
KOSIS_BASE_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"

KOSIS_FLOUR_PARAMS = "orgId=101&tblId=DT_1J22001&objL1=T10&objL2=A01108&itmId=T&prdSe=M&newEstPrdCnt=120"
KOSIS_SUGAR_PARAMS = "orgId=101&tblId=DT_1J22001&objL1=T10&objL2=A01808&itmId=T&prdSe=M&newEstPrdCnt=120"
KOSIS_OIL_PARAMS = "orgId=101&tblId=DT_1J22001&objL1=T10&objL2=A01502&itmId=T&prdSe=M&newEstPrdCnt=120"

# 선택 사항
FAO_CSV_URL = ""
EXCHANGE_RATE_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXKOUS"
```

API 키는 GitHub에 올리지 마세요. 실제 키는 Streamlit Secrets 또는 Render 환경변수에만 저장해야 합니다.
KOSIS API 키는 마지막 `=` 문자까지 포함해 한 줄로 붙여넣어야 합니다. 앞뒤 공백이나 줄바꿈이 들어가면 KOSIS가 `유효하지 않은 인증KEY` 오류를 반환할 수 있습니다.

## 로컬 실행

로컬에서 실행하려면 `.streamlit/secrets.toml` 파일을 만들고 위 Secrets 값을 넣습니다.

```powershell
cd "C:\Users\yis05\Documents\Codex\2026-06-10\new-chat\outputs\collusion_dashboard"
.\.venv\Scripts\python.exe -m streamlit run app.py
```

접속:

```text
http://localhost:8501
```

## 공개 웹 배포: Streamlit Community Cloud

1. 이 폴더의 파일들을 GitHub 저장소에 올립니다.
2. [Streamlit Community Cloud](https://share.streamlit.io/)에 로그인합니다.
3. `New app`을 선택합니다.
4. GitHub 저장소, 브랜치, 메인 파일 `app.py`를 선택합니다.
5. `Advanced settings` 또는 배포 후 `App settings > Secrets`에 KOSIS 값을 넣습니다.
6. Deploy를 누릅니다.

배포가 끝나면 다음과 같은 공개 주소가 생깁니다.

```text
https://your-app-name.streamlit.app
```

## 공개 웹 배포: Render

이 프로젝트에는 Render용 `render.yaml`, `Procfile`, `runtime.txt`가 포함되어 있습니다.

Build Command:

```text
pip install -r requirements.txt
```

Start Command:

```text
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

Render의 `Environment` 메뉴에서 아래 환경변수를 추가합니다.

```text
KOSIS_API_KEY=발급받은_KOSIS_API_키
KOSIS_BASE_URL=https://kosis.kr/openapi/Param/statisticsParameterData.do
KOSIS_FLOUR_PARAMS=orgId=101&tblId=DT_1J22001&objL1=T10&objL2=A01108&itmId=T&prdSe=M&newEstPrdCnt=120
KOSIS_SUGAR_PARAMS=orgId=101&tblId=DT_1J22001&objL1=T10&objL2=A01808&itmId=T&prdSe=M&newEstPrdCnt=120
KOSIS_OIL_PARAMS=orgId=101&tblId=DT_1J22001&objL1=T10&objL2=A01502&itmId=T&prdSe=M&newEstPrdCnt=120
FAO_CSV_URL=
EXCHANGE_RATE_CSV_URL=https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXKOUS
```

## 점수 계산

최근 rolling 기간에 대해 다음 신호를 합산합니다.

- 환율반영 국제 원가지수와 국내 가격지수의 상관계수 약화
- 정규화된 가격 괴리 확대
- Isolation Forest 기반 이상치 비율

환율반영 국제 원가지수는 다음 방식으로 계산합니다.

```text
환율지수_t = 원달러환율_t / 기준월 원달러환율 × 100
환율반영 국제원가지수_t = FAO 국제가격지수_t × 환율지수_t / 100
```

결과는 0~100점입니다.

- 0~39: 정상 범위
- 40~69: 주의
- 70~100: 강한 의심

## 주의

KOSIS와 FAO 데이터는 월별 공식 통계입니다. 앱은 실행 시점에 최신 공개 데이터를 다시 가져오지만, 초 단위 시장 가격처럼 변하는 실시간 호가 데이터는 아닙니다.
