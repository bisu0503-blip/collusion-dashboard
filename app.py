from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from collusion_core import merge_market_data, rolling_risk, summarize_risk
from data_sources import EXCHANGE_RATE_CSV_URL, FAO_FOOD_PRICE_PAGE, load_fao_product_krw, load_kosis

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None


st.set_page_config(page_title="AI 기반 시장 이상 신호 대시보드", layout="wide")

DEFAULT_KOSIS_PARAMS = {
    "flour": "orgId=101&tblId=DT_1J22001&objL1=T10&objL2=A01108&itmId=T&prdSe=M&newEstPrdCnt=120",
    "sugar": "orgId=101&tblId=DT_1J22001&objL1=T10&objL2=A01808&itmId=T&prdSe=M&newEstPrdCnt=120",
    "oil": "orgId=101&tblId=DT_1J22001&objL1=T10&objL2=A01502&itmId=T&prdSe=M&newEstPrdCnt=120",
}


def get_secret(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


def get_product_secret(product: str, suffix: str, default: str = "") -> str:
    return get_secret(f"KOSIS_{product.upper()}_{suffix}", default)


@st.cache_data(show_spinner=False, ttl=300)
def load_market(
    product: str,
    kosis_config: dict,
    fao_csv_url: str | None,
    exchange_csv_url: str | None,
) -> tuple[pd.DataFrame, str, str]:
    global_df, resolved_fao_url, resolved_exchange_url = load_fao_product_krw(
        product,
        csv_url=fao_csv_url,
        exchange_csv_url=exchange_csv_url,
    )
    korea_df = load_kosis(kosis_config["api_key"], kosis_config["base_url"], kosis_config["params"])
    return merge_market_data(global_df, korea_df), resolved_fao_url, resolved_exchange_url


def probability_color(value: float) -> str:
    if value >= 70:
        return "#d62728"
    if value >= 40:
        return "#f2a900"
    return "#2ca02c"


def draw_price_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["Date"], y=df["Global_norm"], name="환율 반영 FAO 원화 기준 지수", mode="lines+markers"))
    fig.add_trace(go.Scatter(x=df["Date"], y=df["Korea_norm"], name="KOSIS 국내 가격지수", mode="lines+markers"))
    fig.update_layout(
        height=430,
        margin=dict(l=20, r=20, t=40, b=20),
        yaxis_title="정규화 지수",
        xaxis_title="월",
        hovermode="x unified",
    )
    return fig


def draw_risk_chart(risk_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=risk_df["Date"],
            y=risk_df["Probability"],
            name="AI 기반 시장 이상 신호 점수",
            mode="lines+markers",
            line=dict(color="#d62728", width=3),
        )
    )
    fig.add_hrect(y0=70, y1=100, fillcolor="#ffdddd", opacity=0.45, line_width=0)
    fig.add_hrect(y0=40, y1=70, fillcolor="#fff0cc", opacity=0.45, line_width=0)
    fig.update_layout(
        height=430,
        margin=dict(l=20, r=20, t=40, b=20),
        yaxis_title="이상 신호 점수",
        xaxis_title="월",
        yaxis=dict(range=[0, 100]),
        hovermode="x unified",
    )
    return fig


st.title("AI 기반 시장 이상 신호 대시보드")
st.caption("KOSIS OpenAPI, FAO 공식 월별 식량가격지수, 원/달러 환율을 수집해 국내 가격과 원화 기준 국제 원가의 괴리를 분석합니다.")

with st.sidebar:
    st.header("실시간 데이터 설정")
    product_label = st.radio("품목", ["밀가루", "설탕", "식용유"], horizontal=True)
    product_map = {"밀가루": "flour", "설탕": "sugar", "식용유": "oil"}
    product = product_map[product_label]

    secret_api_key = get_secret("KOSIS_API_KEY")
    secret_base_url = get_secret("KOSIS_BASE_URL", "https://kosis.kr/openapi/Param/statisticsParameterData.do")
    secret_params = get_product_secret(product, "PARAMS", DEFAULT_KOSIS_PARAMS[product])
    secret_fao_csv_url = get_secret("FAO_CSV_URL")
    secret_exchange_csv_url = get_secret("EXCHANGE_RATE_CSV_URL", EXCHANGE_RATE_CSV_URL)

    if secret_api_key and secret_params:
        st.success("배포 Secrets의 KOSIS 설정을 사용 중입니다.")
    else:
        st.warning("KOSIS API Key와 품목 파라미터가 필요합니다.")

    with st.expander("KOSIS OpenAPI 설정", expanded=not (secret_api_key and secret_params)):
        api_key = st.text_input("KOSIS API Key", value=secret_api_key, type="password")
        base_url = st.text_input("KOSIS API URL", value=secret_base_url)
        params = st.text_area(
            "선택 품목 KOSIS 파라미터",
            value=secret_params,
            height=120,
            placeholder="orgId=...&tblId=...&itmId=...&objL1=...&prdSe=M&newEstPrdCnt=120",
        )

    with st.expander("FAO 수집 설정"):
        st.markdown(f"FAO 공식 페이지: [{FAO_FOOD_PRICE_PAGE}]({FAO_FOOD_PRICE_PAGE})")
        fao_csv_url = st.text_input(
            "FAO CSV URL 비워두면 공식 페이지에서 자동 탐색",
            value=secret_fao_csv_url,
        ).strip() or None

    with st.expander("환율 수집 설정"):
        exchange_csv_url = st.text_input(
            "원/달러 환율 URL",
            value=secret_exchange_csv_url,
            help="기본값은 Yahoo Finance USDKRW=X 일별 환율이며, 앱에서 월평균으로 변환합니다.",
        ).strip() or None

    st.header("모델 설정")
    refresh_seconds = st.slider("자동 갱신 주기(초)", 60, 3600, 300, 60)
    window_months = st.slider("Rolling 분석 기간(개월)", 6, 60, 18)
    max_lag = st.slider("최대 가격 반영 지연(개월)", 0, 12, 6)

    if st.button("캐시 초기화 후 새로고침"):
        st.cache_data.clear()
        st.rerun()

if st_autorefresh is not None:
    st_autorefresh(interval=refresh_seconds * 1000, key="data_refresh")
else:
    st.info("자동 갱신을 쓰려면 `streamlit-autorefresh`를 설치하세요. 현재는 수동 새로고침으로 동작합니다.")

kosis_config = {"api_key": api_key, "base_url": base_url, "params": params}

try:
    df, resolved_fao_url, resolved_exchange_url = load_market(product, kosis_config, fao_csv_url, exchange_csv_url)
except Exception as exc:
    st.error(f"실시간 데이터를 불러오지 못했습니다: {exc}")
    st.stop()

if len(df) < 4:
    st.warning("분석 가능한 공통 월 데이터가 너무 적습니다.")
    st.dataframe(df, use_container_width=True)
    st.stop()

risk_df = rolling_risk(df, window_months=window_months, max_lag=max_lag)
summary = summarize_risk(df.tail(window_months), max_lag=max_lag)
latest_date = df["Date"].max().strftime("%Y-%m")

col1, col2, col3, col4 = st.columns(4)
col1.metric("현재 AI 기반 시장 이상 신호 점수", f"{summary.probability:.2f} / 100", summary.level)
col2.metric(
    "최적 지연",
    f"{summary.best_lag}개월",
    help=(
        "환율을 반영한 FAO 국제 원가 변화가 국내 가격에 몇 개월 뒤 가장 비슷하게 "
        "나타나는지를 뜻합니다. 예를 들어 4개월이면 국제 원가 변화와 국내 가격 변화가 "
        "4개월 차이를 두고 가장 잘 맞았다는 의미입니다."
    ),
)
col3.metric(
    "최대 상관계수",
    f"{summary.best_corr:.3f}",
    help=(
        "최적 지연을 적용했을 때 환율반영 국제원가지수와 국내 가격지수가 얼마나 같은 방향으로 "
        "움직였는지를 나타냅니다. 1에 가까울수록 함께 움직이고, 0에 가까울수록 관련성이 약하며, "
        "음수이면 반대 방향으로 움직인다는 뜻입니다."
    ),
)
col4.metric("최근 공통 데이터", latest_date)

st.caption(f"FAO 데이터 출처: {resolved_fao_url}")
st.caption(f"환율 데이터 출처: {resolved_exchange_url}")

gauge = go.Figure(
    go.Indicator(
        mode="gauge+number",
        value=summary.probability,
        number={"suffix": " / 100"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": probability_color(summary.probability)},
            "steps": [
                {"range": [0, 40], "color": "#e8f5e9"},
                {"range": [40, 70], "color": "#fff8e1"},
                {"range": [70, 100], "color": "#ffebee"},
            ],
        },
    )
)
gauge.update_layout(height=260, margin=dict(l=20, r=20, t=20, b=20))
st.plotly_chart(gauge, use_container_width=True)

left, right = st.columns(2)
with left:
    st.subheader("환율 반영 FAO 국제 원가 vs KOSIS 국내 가격")
    st.plotly_chart(draw_price_chart(df), use_container_width=True)

with right:
    st.subheader("Rolling AI 기반 시장 이상 신호 점수")
    st.plotly_chart(draw_risk_chart(risk_df), use_container_width=True)

st.subheader("최근 위험 신호")
view = df.merge(risk_df, on="Date", how="left")
view = view[
    [
        "Date",
        "FAO_Global",
        "ExchangeRate",
        "ExchangeIndex",
        "Global",
        "Korea",
        "gap",
        "pass_through_gap",
        "Probability",
        "Level",
    ]
].tail(24)
view["Date"] = view["Date"].dt.strftime("%Y-%m")
view = view.rename(
    columns={
        "FAO_Global": "FAO 원지수",
        "ExchangeRate": "원/달러 환율",
        "ExchangeIndex": "환율지수",
        "Global": "환율반영 국제원가지수",
        "Korea": "국내 가격지수",
        "gap": "가격 괴리도",
        "pass_through_gap": "변화율 괴리도",
    }
)
st.dataframe(view.sort_values("Date", ascending=False), use_container_width=True, hide_index=True)

st.caption(
    "이 점수는 조사 우선순위 지표이며 법적 의미의 담합 판정이 아닙니다. "
    "KOSIS와 FAO는 월별 공식 데이터라서 새 값은 각 기관의 월별 갱신 후 반영됩니다."
)

st.markdown("---")
st.info(
    "본 서비스는 공개된 통계자료 및 데이터 분석 결과를 기반으로 시장 가격 변동 패턴을 "
    "시각화·분석하는 참고용 정보 서비스입니다.\n\n"
    "본 서비스에서 제공하는 분석 결과, 이상 신호 점수 및 예측 결과는 "
    "통계적·기계학습적 분석에 따른 참고 지표일 뿐이며, 특정 기업 또는 기관의 담합, "
    "불공정거래, 위법행위 여부를 판단하거나 확정하는 근거로 사용될 수 없습니다.\n\n"
    "서비스 이용자는 본 분석 결과를 참고자료로만 활용하여야 하며, "
    "최종 판단과 책임은 이용자에게 있습니다."
)

with st.expander("AI 기반 시장 이상 신호 점수 알고리즘 설명", expanded=True):
    st.markdown(
        """
        이 대시보드의 AI 기반 시장 이상 신호 점수는 국내 가격이 환율을 반영한 국제 원재료 원가 흐름과 얼마나 다르게 움직이는지를
        통계적으로 요약한 지표입니다. 점수는 특정 기업의 담합 여부를 판단하는 값이 아니라,
        가격 흐름상 추가 검토가 필요한 시점을 찾기 위한 참고용 위험 신호입니다.

        **1. 데이터 수집**

        - 국내 가격: KOSIS OpenAPI의 월별 소비자물가지수
        - 밀가루 국내 지표: `DT_1J22001`, 전국 `T10`, 밀가루 `A01108`
        - 설탕 국내 지표: `DT_1J22001`, 전국 `T10`, 설탕 `A01808`
        - 식용유 국내 지표: `DT_1J22001`, 전국 `T10`, 식용유 `A01502`
        - 국제 가격: FAO Food Price Index의 월별 Cereals, Sugar 또는 Oils 지수
        - 환율: 원/달러 일별 환율을 월평균으로 변환한 값

        **2. 날짜 기준 병합**

        KOSIS와 FAO 데이터는 월 단위로 제공되고, 환율은 일별 데이터를 월평균으로 변환합니다.
        이후 국내 가격, FAO 국제 가격, 원/달러 환율이 모두 존재하는 월만 남겨 비교합니다.

        **3. 환율 반영 국제 원가 계산**

        FAO 국제 가격지수는 달러 기준 국제 시장 흐름을 보여주지만, 국내 수입 원가에는 원/달러 환율이 함께 작용합니다.
        그래서 원/달러 환율을 기준 시점 대비 지수로 바꾼 뒤 FAO 지수에 곱합니다.

        ```text
        환율지수_t = 원달러환율_t / 기준월 원달러환율 × 100

        환율반영 국제원가지수_t =
          FAO 국제가격지수_t × 환율지수_t / 100
        ```

        예를 들어 FAO 가격이 그대로여도 원/달러 환율이 10% 오르면, 원화 기준 국제 원가는 약 10% 상승한 것으로 반영됩니다.

        **4. 정규화**

        국내 지수와 환율반영 국제원가지수는 기준연도와 단위가 다르기 때문에 직접 비교할 수 없습니다.
        그래서 각각의 값을 0~1 범위로 변환합니다.

        ```text
        정규화값 = (현재값 - 최솟값) / (최댓값 - 최솟값)
        ```

        이렇게 하면 국내 가격과 원화 기준 국제 원가의 절대 수준이 아니라, 기간 안에서의 상대적 움직임을 비교할 수 있습니다.

        **5. 가격 연동성 분석**

        일반적으로 밀가루, 설탕, 식용유 같은 식품 가격은 국제 곡물·설탕·식물성유지 가격과 환율의 영향을 어느 정도 받습니다.
        따라서 환율반영 국제원가지수와 국내 가격의 상관계수를 계산합니다. 상관계수가 낮거나 음수에 가까우면
        국내 가격이 원화 기준 국제 원가 흐름과 다르게 움직인다는 의미로 보고 위험 신호를 높입니다.

        단, 국내 가격은 국제 가격을 즉시 반영하지 않을 수 있으므로 0~최대 지연 개월 수까지
        lag 분석을 합니다. 예를 들어 최대 지연을 6개월로 설정하면, 원화 기준 국제 원가 변화가 국내 가격에
        0개월 뒤, 1개월 뒤, ..., 6개월 뒤 반영되는 경우를 모두 비교하고 가장 높은 상관계수를 선택합니다.

        **6. 가격 괴리도 계산**

        정규화된 국내 가격과 환율반영 국제원가지수의 차이를 월별로 계산합니다.

        ```text
        가격 괴리도 = |국내 정규화 지수 - 환율반영 국제원가 정규화 지수|
        ```

        이 값이 클수록 원화 기준 국제 원가 흐름과 국내 소비자 가격 흐름 사이의 차이가 크다는 뜻입니다.

        **7. 이상치 탐지**

        국내 가격 정규화값과 가격 괴리도를 함께 사용해 이상치를 탐지합니다.
        scikit-learn이 설치된 환경에서는 Isolation Forest를 사용하고, 사용할 수 없는 환경에서는
        z-score 기반의 간단한 이상치 탐지를 사용합니다.

        이상치 비율이 높다는 것은 분석 기간 안에서 평소와 다른 가격 움직임이 자주 나타났다는 뜻입니다.

        **8. 최종 점수 계산**

        최종 점수는 세 가지 위험 신호를 가중합해 0~100점으로 변환합니다.

        ```text
        상관 위험 = 1 - max(상관계수, 0)
        괴리 위험 = min(평균 가격 괴리도 / 0.35, 1)
        이상치 위험 = min(이상치 비율 / 0.2, 1)

        AI 기반 시장 이상 신호 점수 =
          (상관 위험 × 0.40 + 괴리 위험 × 0.35 + 이상치 위험 × 0.25) × 100
        ```

        현재 가중치는 상관계수 약화 40%, 가격 괴리 35%, 이상치 비율 25%입니다.
        즉 원화 기준 국제 원가와 국내 가격의 연동성이 약해지는 현상을 가장 크게 보고,
        그 다음으로 가격 괴리와 이상치 발생을 반영합니다.

        **9. 점수 해석**

        - 0~39점: 정상 범위
        - 40~69점: 주의
        - 70~100점: 강한 이상 신호

        이 점수는 시장 가격의 비정상적 움직임을 찾기 위한 통계적 신호입니다.
        실제 담합 여부를 판단하려면 입찰자료, 기업 간 관계, 공정거래위원회 사건 이력,
        가격 결정 구조, 유통 비용, 세금, 정책 변화 같은 추가 자료와 함께 검토해야 합니다.
        """
    )
