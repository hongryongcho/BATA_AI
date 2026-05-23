"""
Plotly 차트 함수 모듈
"""
from __future__ import annotations

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots


COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]


# ── 누적 수익률 곡선 ─────────────────────────────────────────────

def plot_cumulative_returns(backtest_df: pd.DataFrame) -> go.Figure:
    if backtest_df.empty or "총자산" not in backtest_df.columns:
        return _empty_fig("백테스트 데이터 없음")

    df = backtest_df.dropna(subset=["날짜", "총자산"]).copy()
    initial = df["총자산"].iloc[0]
    df["누적수익률(%)"] = (df["총자산"] / initial - 1) * 100

    from metrics import calc_drawdown_series
    dd = calc_drawdown_series(df["총자산"])

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.7, 0.3],
                        subplot_titles=("누적 수익률", "낙폭 (Drawdown)"),
                        vertical_spacing=0.06)

    fig.add_trace(go.Scatter(
        x=df["날짜"], y=df["누적수익률(%)"],
        mode="lines", name="누적수익률",
        line=dict(color=COLORS[0], width=2),
        fill="tozeroy", fillcolor="rgba(31,119,180,0.1)"
    ), row=1, col=1)

    # 매수/매도 마커
    if "매매구분" in df.columns:
        buys = df[df["매매구분"].str.contains("BUY|매수", na=False, case=False)]
        sells = df[df["매매구분"].str.contains("SELL|매도", na=False, case=False)]
        fig.add_trace(go.Scatter(
            x=buys["날짜"], y=(buys["총자산"] / initial - 1) * 100,
            mode="markers", name="매수",
            marker=dict(color="#2ca02c", size=8, symbol="triangle-up")
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=sells["날짜"], y=(sells["총자산"] / initial - 1) * 100,
            mode="markers", name="매도",
            marker=dict(color="#d62728", size=8, symbol="triangle-down")
        ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df["날짜"], y=dd.values,
        mode="lines", name="낙폭",
        line=dict(color="#d62728", width=1),
        fill="tozeroy", fillcolor="rgba(214,39,40,0.2)"
    ), row=2, col=1)

    fig.update_layout(
        height=500, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        hovermode="x unified", margin=dict(l=0, r=0, t=40, b=0)
    )
    fig.update_yaxes(ticksuffix="%", row=1, col=1)
    fig.update_yaxes(ticksuffix="%", row=2, col=1)
    return fig


# ── 백테스트 종가/RSI/낙폭 차트 ────────────────────────────────

def plot_backtest_price(df: pd.DataFrame, ticker: str) -> go.Figure:
    """종가 + RSI(2) + 전고점낙폭 3단 차트"""
    if df.empty or "close" not in df.columns:
        return _empty_fig("데이터 없음")

    has_rsi = "rsi2" in df.columns
    has_chg = "chg_pct" in df.columns
    n_rows = 1 + (1 if has_rsi else 0) + (1 if has_chg else 0)

    if n_rows == 3:
        heights = [0.55, 0.25, 0.20]
    elif n_rows == 2:
        heights = [0.65, 0.35]
    else:
        heights = [1.0]

    titles = [f"{ticker} 종가($)"]
    if has_rsi:
        titles.append("RSI(2)")
    if has_chg:
        titles.append("전고점 낙폭(%)")

    fig = make_subplots(rows=n_rows, cols=1, shared_xaxes=True,
                        row_heights=heights, subplot_titles=titles,
                        vertical_spacing=0.06)

    fig.add_trace(go.Scatter(
        x=df["날짜"], y=df["close"],
        mode="lines", name="종가",
        line=dict(color=COLORS[0], width=2)
    ), row=1, col=1)

    if "buy_limit_expected_px" in df.columns:
        mask = df["buy_limit_expected_px"].notna() & (df["buy_limit_expected_px"] > 0)
        if mask.any():
            fig.add_trace(go.Scatter(
                x=df.loc[mask, "날짜"], y=df.loc[mask, "buy_limit_expected_px"],
                mode="markers", name="매수 예상가",
                marker=dict(color="#2ca02c", size=5, symbol="triangle-up")
            ), row=1, col=1)

    if "sell_limit_expected_px" in df.columns:
        mask = df["sell_limit_expected_px"].notna() & (df["sell_limit_expected_px"] > 0)
        if mask.any():
            fig.add_trace(go.Scatter(
                x=df.loc[mask, "날짜"], y=df.loc[mask, "sell_limit_expected_px"],
                mode="markers", name="매도 예상가",
                marker=dict(color="#d62728", size=5, symbol="triangle-down")
            ), row=1, col=1)

    rsi_row = 2
    if has_rsi:
        fig.add_trace(go.Scatter(
            x=df["날짜"], y=df["rsi2"],
            mode="lines", name="RSI(2)",
            line=dict(color=COLORS[2], width=1.5)
        ), row=rsi_row, col=1)
        fig.add_hline(y=10, line_dash="dot", line_color="#2ca02c", opacity=0.7,
                      row=rsi_row, col=1)
        fig.add_hline(y=90, line_dash="dot", line_color="#d62728", opacity=0.7,
                      row=rsi_row, col=1)
        fig.update_yaxes(range=[0, 100], row=rsi_row, col=1)

    chg_row = rsi_row + (1 if has_rsi else 0)
    if has_chg:
        fig.add_trace(go.Scatter(
            x=df["날짜"], y=df["chg_pct"],
            mode="lines", name="낙폭(%)",
            line=dict(color="#d62728", width=1),
            fill="tozeroy", fillcolor="rgba(214,39,40,0.15)"
        ), row=chg_row, col=1)
        fig.update_yaxes(ticksuffix="%", row=chg_row, col=1)

    fig.update_layout(
        height=560, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        hovermode="x unified", margin=dict(l=0, r=0, t=40, b=0)
    )
    return fig


# ── 사이클별 수익률 바차트 ───────────────────────────────────────

def plot_cycle_returns(backtest_df: pd.DataFrame) -> go.Figure:
    if backtest_df.empty or "사이클" not in backtest_df.columns:
        return _empty_fig("사이클 데이터 없음")

    df = backtest_df.dropna(subset=["사이클", "총자산"]).copy()
    cycle_data = []
    for cycle_id, grp in df.groupby("사이클", sort=True):
        grp = grp.sort_values("날짜")
        start = grp["총자산"].iloc[0]
        end = grp["총자산"].iloc[-1]
        ret = (end - start) / start * 100 if start > 0 else 0.0
        cycle_data.append({"사이클": int(cycle_id), "수익률(%)": ret})

    if not cycle_data:
        return _empty_fig("사이클 데이터 없음")

    cdf = pd.DataFrame(cycle_data)
    colors = ["#2ca02c" if v >= 0 else "#d62728" for v in cdf["수익률(%)"]]

    fig = go.Figure(go.Bar(
        x=cdf["사이클"], y=cdf["수익률(%)"],
        marker_color=colors, name="사이클 수익률"
    ))
    fig.update_layout(
        title="사이클별 수익률", template="plotly_dark",
        xaxis_title="사이클", yaxis_title="수익률 (%)",
        height=380, margin=dict(l=0, r=0, t=40, b=0)
    )
    fig.update_yaxes(ticksuffix="%")
    return fig


# ── 월별 수익률 히트맵 ──────────────────────────────────────────

def plot_monthly_heatmap(monthly_pivot: pd.DataFrame) -> go.Figure:
    if monthly_pivot.empty:
        return _empty_fig("월별 수익률 데이터 없음")

    z = monthly_pivot.values
    x = list(monthly_pivot.columns)
    y = [str(yr) for yr in monthly_pivot.index]

    text = [[f"{v:.1f}%" if not np.isnan(v) else "" for v in row] for row in z]

    fig = go.Figure(go.Heatmap(
        z=z, x=x, y=y, text=text, texttemplate="%{text}",
        colorscale=[
            [0.0, "#d62728"], [0.4, "#8B0000"],
            [0.5, "#1a1e2e"],
            [0.6, "#1a6b2a"], [1.0, "#2ca02c"]
        ],
        zmid=0, colorbar=dict(title="수익률%"),
        hoverongaps=False,
    ))
    fig.update_layout(
        title="월별 수익률 히트맵", template="plotly_dark",
        height=max(250, len(y) * 40 + 80),
        margin=dict(l=0, r=0, t=40, b=0)
    )
    return fig


# ── 커스텀 멀티 시리즈 차트 ────────────────────────────────────

def plot_custom_chart(
    series_dict: dict[str, pd.Series],
    normalize: bool = True,
) -> go.Figure:
    if not series_dict:
        return _empty_fig("시리즈를 선택하세요")

    # RSI 계열은 별도 Y축 처리
    RSI_SERIES = {"RSI(2)", "RSI(14)", "Fear&Greed"}
    main_series = {k: v for k, v in series_dict.items() if k not in RSI_SERIES}
    rsi_series = {k: v for k, v in series_dict.items() if k in RSI_SERIES}

    has_rsi = bool(rsi_series)
    fig = make_subplots(
        rows=2 if has_rsi else 1, cols=1,
        shared_xaxes=True,
        row_heights=[0.65, 0.35] if has_rsi else [1.0],
        vertical_spacing=0.06
    )

    for i, (name, s) in enumerate(main_series.items()):
        if normalize:
            first = s.iloc[0]
            y = (s / first - 1) * 100 if first != 0 else s
            yaxis_label = "% 변화율"
        else:
            y = s
            yaxis_label = "원본값"

        fig.add_trace(go.Scatter(
            x=s.index, y=y, mode="lines", name=name,
            line=dict(color=COLORS[i % len(COLORS)], width=2)
        ), row=1, col=1)

    for i, (name, s) in enumerate(rsi_series.items()):
        col = COLORS[(len(main_series) + i) % len(COLORS)]
        fig.add_trace(go.Scatter(
            x=s.index, y=s, mode="lines", name=name,
            line=dict(color=col, width=1.5)
        ), row=2 if has_rsi else 1, col=1)

    if has_rsi:
        # RSI 기준선 (30/70)
        fig.add_hline(y=30, line_dash="dot", line_color="gray", row=2, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="gray", row=2, col=1)
        fig.update_yaxes(title_text="RSI / FnG", row=2, col=1, range=[0, 100])

    fig.update_layout(
        height=480, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        hovermode="x unified", margin=dict(l=0, r=0, t=20, b=0)
    )
    if normalize and main_series:
        fig.update_yaxes(ticksuffix="%", row=1, col=1)

    return fig


# ── 포트폴리오 파이차트 ─────────────────────────────────────────

def plot_portfolio_pie(positions: list[dict]) -> go.Figure:
    if not positions:
        return _empty_fig("포지션 없음")

    labels = [p["ticker"] for p in positions]
    values = [p["market_value"] for p in positions]

    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        hole=0.4, textinfo="label+percent",
        marker=dict(colors=COLORS[:len(labels)])
    ))
    fig.update_layout(
        title="포트폴리오 비중", template="plotly_dark",
        height=350, margin=dict(l=0, r=0, t=40, b=0)
    )
    return fig


# ── RSI 게이지 ──────────────────────────────────────────────────

def plot_gauge(value: float, title: str, min_val=0, max_val=100,
               danger_low=20, danger_high=80) -> go.Figure:
    if value <= danger_low:
        color = "#2ca02c"
    elif value >= danger_high:
        color = "#d62728"
    else:
        color = "#1f77b4"

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        title={"text": title, "font": {"size": 16}},
        gauge={
            "axis": {"range": [min_val, max_val]},
            "bar": {"color": color},
            "steps": [
                {"range": [0, danger_low], "color": "rgba(44,160,44,0.2)"},
                {"range": [danger_high, 100], "color": "rgba(214,39,40,0.2)"},
            ],
            "threshold": {
                "line": {"color": "white", "width": 2},
                "thickness": 0.75, "value": value
            }
        }
    ))
    fig.update_layout(
        height=220, template="plotly_dark",
        margin=dict(l=20, r=20, t=40, b=20)
    )
    return fig


# ── 유틸 ────────────────────────────────────────────────────────

def _empty_fig(msg: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper",
                       x=0.5, y=0.5, showarrow=False,
                       font=dict(size=16, color="gray"))
    fig.update_layout(template="plotly_dark", height=300,
                      margin=dict(l=0, r=0, t=0, b=0))
    return fig
