from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from collusion_core import merge_market_data, rolling_risk, summarize_risk
from data_sources import FAO_FOOD_PRICE_PAGE, load_fao_product, load_kosis

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None


st.set_page_config(page_title="담합 의심 실시간 대시보드", layout="wide")

DEFAULT_KOSIS_PARAMS = {
    "flour": "orgId=101&tblId=DT_1J22001&objL1=T10&objL2=A01108&itmId=T&prdSe=M&newEstPrdCnt=120",
    "sugar": "orgId=101&tblId=DT_1J22001&objL1=T10&objL2=A01808&itmId=T&prdSe=M&newEstPrdCnt=120",
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
def load_market(product: str, kosis_config: dict, fao_csv_url: str | None) -> tuple[pd.DataFrame, str]:
    global_df, resolved_fao_url = load_fao_product(product, csv_url=fao_csv_url)
    korea_df = load_kosis(kosis_config["api_key"], kosis_config["base_url"], kosis_config["params"])
    return merge_market_data(global_df, korea_df), resolved_fao_url


def probability_color(value: float) -> str:
    if value >= 70:
        return "#d62728"
    if value >= 40:
        return "#f2a900"
    return "#2ca02c"


def draw_price_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["Date"], y=df["Global_norm"], name="FAO 국제 원재료 지수", mode="lines+markers"))
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
            name="담합 의심 점수",
            mode="lines+markers",
            line=dict(color="#d62728", width=3),
        )
    )
    fig.add_hrect(y0=70, y1=100, fillcolor="#ffdddd", opacity=0.45, line_width=0)
    fig.add_hrect(y0=40, y1=70, fillcolor="#fff0cc", opacity=0.45, line_width=0)
    fig.update_layout(
        height=430,
        margin=dict(l=20, r=20, t=40, b=20),
        yaxis_title="의심 점수",
        xaxis_title="월",
        yaxis=dict(range=[0, 100]),
        hovermode="x unified",
    )
    return fig


st.title("담합 의심 실시간 대시보드")
st.caption("KOSIS OpenAPI와 FAO 공식 월별 식량가격지수를 실시간으로 수집해 국내 가격과 국제 가격의 괴리를 분석합니다.")

with st.sidebar:
    st.header("실시간 데이터 설정")
    product_label = st.radio("품목", ["밀가루", "설탕"], horizontal=True)
    product = "flour" if product_label == "밀가루" else "sugar"

    secret_api_key = get_secret("KOSIS_API_KEY")
    secret_base_url = get_secret("KOSIS_BASE_URL", "https://kosis.kr/openapi/Param/statisticsParameterData.do")
    secret_params = get_product_secret(product, "PARAMS", DEFAULT_KOSIS_PARAMS[product])
    secret_fao_csv_url = get_secret("FAO_CSV_URL")

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
    df, resolved_fao_url = load_market(product, kosis_config, fao_csv_url)
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
col1.metric("현재 담합 의심 점수", f"{summary.probability:.2f} / 100", summary.level)
col2.metric("최적 지연", f"{summary.best_lag}개월")
col3.metric("최대 상관계수", f"{summary.best_corr:.3f}")
col4.metric("최근 공통 데이터", latest_date)

st.caption(f"FAO 데이터 출처: {resolved_fao_url}")

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
    st.subheader("FAO 국제 가격 vs KOSIS 국내 가격")
    st.plotly_chart(draw_price_chart(df), use_container_width=True)

with right:
    st.subheader("Rolling 담합 의심 점수")
    st.plotly_chart(draw_risk_chart(risk_df), use_container_width=True)

st.subheader("최근 위험 신호")
view = df.merge(risk_df, on="Date", how="left")
view = view[["Date", "Global", "Korea", "gap", "pass_through_gap", "Probability", "Level"]].tail(24)
view["Date"] = view["Date"].dt.strftime("%Y-%m")
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
