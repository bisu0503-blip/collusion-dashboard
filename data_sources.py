from __future__ import annotations

import re
from io import BytesIO
from urllib.parse import parse_qsl, urljoin

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


FAO_FOOD_PRICE_PAGE = "https://www.fao.org/worldfoodsituation/foodpricesindex/en/"
FAO_FALLBACK_CSV_URL = (
    "https://www.fao.org/media/docs/worldfoodsituationlibraries/default-document-library/"
    "food_price_indices_data.csv?download=true"
)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml,text/csv,application/json,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "close",
}


def _session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1.2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _get(url: str, **kwargs) -> requests.Response:
    try:
        response = _session().get(url, timeout=kwargs.pop("timeout", 45), **kwargs)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        raise RuntimeError(f"External data request failed: {url} ({exc})") from exc


def discover_fao_csv_url(page_url: str = FAO_FOOD_PRICE_PAGE) -> str:
    try:
        response = _get(page_url, timeout=30)
    except RuntimeError:
        return FAO_FALLBACK_CSV_URL

    matches = re.findall(r'href=["\']([^"\']*food_price_indices_data[^"\']*\.csv[^"\']*)["\']', response.text)
    if matches:
        return urljoin(page_url, matches[0].replace("&amp;", "&"))

    matches = re.findall(r'href=["\']([^"\']*\.csv[^"\']*)["\']', response.text)
    if matches:
        return urljoin(page_url, matches[0].replace("&amp;", "&"))

    return FAO_FALLBACK_CSV_URL


def _read_fao_csv(csv_url: str) -> pd.DataFrame:
    response = _get(csv_url, timeout=45)
    content = response.content

    for header in (0, 1, 2):
        try:
            df = pd.read_csv(BytesIO(content), header=header)
            df.columns = df.columns.astype(str).str.strip()
            if "Month" in df.columns or "Date" in df.columns:
                return df
        except Exception:
            continue

    raise ValueError("FAO CSV에서 Month/Date 컬럼을 찾지 못했습니다.")


def load_fao_product(product: str, csv_url: str | None = None) -> tuple[pd.DataFrame, str]:
    source_url = csv_url.strip() if csv_url else discover_fao_csv_url()

    column_candidates = {
        "flour": ["Cereals Price Index", "Cereals"],
        "sugar": ["Sugar Price Index", "Sugar"],
    }

    raw = _read_fao_csv(source_url)
    if "Month" in raw.columns:
        raw["Date"] = pd.to_datetime(raw["Month"], format="%b-%y", errors="coerce")
    else:
        raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce")

    column = next((name for name in column_candidates[product] if name in raw.columns), None)
    if column is None:
        raise ValueError(f"FAO 데이터에 필요한 컬럼이 없습니다: {column_candidates[product]}")

    df = raw[["Date", column]].rename(columns={column: "Global"}).dropna()
    df["Global"] = pd.to_numeric(df["Global"], errors="coerce")
    return df.dropna().sort_values("Date"), source_url


def _parse_kosis_date(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()

    parsed = pd.to_datetime(text, format="%Y%m", errors="coerce")
    missing = parsed.isna()
    if missing.any():
        parsed.loc[missing] = pd.to_datetime(text.loc[missing], format="%Y.%m", errors="coerce")

    missing = parsed.isna()
    if missing.any():
        parsed.loc[missing] = pd.to_datetime(text.loc[missing], errors="coerce")

    return parsed


def load_kosis(api_key: str, base_url: str, params_text: str) -> pd.DataFrame:
    if not api_key:
        raise ValueError("KOSIS_API_KEY가 설정되어 있지 않습니다.")
    if not params_text:
        raise ValueError("품목별 KOSIS 파라미터가 설정되어 있지 않습니다.")

    params = dict(parse_qsl(params_text.lstrip("?"), keep_blank_values=True))
    params.pop("apiKey", None)
    params.pop("format", None)
    params.pop("jsonVD", None)
    params.pop("method", None)
    params.update({"method": "getList", "apiKey": api_key, "format": "json", "jsonVD": "Y"})

    response = _get(base_url, params=params, timeout=45)
    data = response.json()

    if isinstance(data, dict) and data.get("err"):
        raise ValueError(f"KOSIS 오류: {data}")
    if not isinstance(data, list):
        raise ValueError(f"KOSIS 응답 형식이 예상과 다릅니다: {data}")

    df = pd.DataFrame(data)
    date_col = next((col for col in ["PRD_DE", "PRD_DE_NM", "Date"] if col in df.columns), None)
    value_col = next((col for col in ["DT", "DATA_VALUE", "VALUE"] if col in df.columns), None)
    if date_col is None or value_col is None:
        raise ValueError("KOSIS 응답에서 날짜/값 컬럼을 찾지 못했습니다.")

    result = pd.DataFrame(
        {
            "Date": _parse_kosis_date(df[date_col]),
            "Korea": pd.to_numeric(df[value_col], errors="coerce"),
        }
    )
    return result.dropna().sort_values("Date")
