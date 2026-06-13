from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

try:
    from sklearn.ensemble import IsolationForest
except Exception:
    IsolationForest = None


@dataclass
class RiskSummary:
    probability: float
    level: str
    best_lag: int
    best_corr: float
    avg_gap: float
    anomaly_ratio: float


def minmax(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    span = values.max() - values.min()
    if pd.isna(span) or span == 0:
        return pd.Series(np.zeros(len(values)), index=values.index)
    return (values - values.min()) / span


def merge_market_data(global_df: pd.DataFrame, korea_df: pd.DataFrame) -> pd.DataFrame:
    df = pd.merge(global_df, korea_df, on="Date", how="inner").sort_values("Date")
    df = df.dropna(subset=["Global", "Korea"]).reset_index(drop=True)
    if df.empty:
        return df

    df["Global_norm"] = minmax(df["Global"])
    df["Korea_norm"] = minmax(df["Korea"])
    df["gap"] = (df["Korea_norm"] - df["Global_norm"]).abs()
    df["Global_mom"] = df["Global"].pct_change()
    df["Korea_mom"] = df["Korea"].pct_change()
    df["pass_through_gap"] = (df["Korea_mom"] - df["Global_mom"]).abs()
    return df


def best_lag_correlation(df: pd.DataFrame, max_lag: int) -> tuple[int, float]:
    lag_corrs: list[tuple[int, float]] = []
    for lag in range(max_lag + 1):
        pair = pd.concat([df["Global_norm"], df["Korea_norm"].shift(lag)], axis=1).dropna()
        if len(pair) < 3:
            continue
        corr = pair.iloc[:, 0].corr(pair.iloc[:, 1])
        if not pd.isna(corr):
            lag_corrs.append((lag, float(corr)))

    if not lag_corrs:
        return 0, 0.0
    return max(lag_corrs, key=lambda item: item[1])


def anomaly_ratio(df: pd.DataFrame) -> float:
    if len(df) < 8:
        return 0.0

    features = df[["Korea_norm", "gap"]].fillna(0)
    if IsolationForest is None:
        z = (features - features.mean()) / features.std(ddof=0).replace(0, np.nan)
        outliers = z.abs().gt(2.5).any(axis=1).fillna(False)
        return float(outliers.mean())

    contamination = min(0.2, max(0.05, 2 / len(features)))
    model = IsolationForest(contamination=contamination, random_state=42)
    labels = model.fit_predict(features)
    return float((labels == -1).mean())


def summarize_risk(df: pd.DataFrame, max_lag: int = 6) -> RiskSummary:
    if len(df) < 4:
        return RiskSummary(0.0, "데이터 부족", 0, 0.0, 0.0, 0.0)

    best_lag, corr = best_lag_correlation(df, max_lag)
    avg_gap = float(df["gap"].mean())
    anomalies = anomaly_ratio(df)

    corr_risk = 1 - max(min(corr, 1.0), 0.0)
    gap_risk = min(avg_gap / 0.35, 1.0)
    anomaly_risk = min(anomalies / 0.2, 1.0)

    score = (corr_risk * 0.40 + gap_risk * 0.35 + anomaly_risk * 0.25) * 100
    probability = round(float(np.clip(score, 0, 100)), 2)

    if probability >= 70:
        level = "강한 이상 신호"
    elif probability >= 40:
        level = "주의"
    else:
        level = "정상 범위"

    return RiskSummary(probability, level, best_lag, round(corr, 3), round(avg_gap, 3), round(anomalies, 3))


def rolling_risk(df: pd.DataFrame, window_months: int = 18, max_lag: int = 6) -> pd.DataFrame:
    rows = []
    if df.empty:
        return pd.DataFrame(columns=["Date", "Probability", "Level", "BestLag", "BestCorr", "AvgGap", "AnomalyRatio"])

    for idx in range(len(df)):
        start = max(0, idx - window_months + 1)
        window = df.iloc[start : idx + 1].copy()
        summary = summarize_risk(window, max_lag=max_lag)
        rows.append(
            {
                "Date": df.loc[idx, "Date"],
                "Probability": summary.probability,
                "Level": summary.level,
                "BestLag": summary.best_lag,
                "BestCorr": summary.best_corr,
                "AvgGap": summary.avg_gap,
                "AnomalyRatio": summary.anomaly_ratio,
            }
        )
    return pd.DataFrame(rows)
