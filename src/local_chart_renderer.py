"""
mplfinance 기반 로컬 차트 렌더링 모듈
- calculate_indicators(): MA(5/20/60/120) + MACD(12,26,9) 계산
- render_chart(): 3-panel 캔들차트 PNG 생성
- BatchChartRenderer: 유니버스 배치 렌더링
"""

import logging
import re
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # 헤드리스 렌더링

import mplfinance as mpf
import pandas as pd
import yfinance as yf

from src.universe_manager import UniverseManager

logger = logging.getLogger(__name__)


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV DataFrame에 기술적 지표 컬럼을 추가한다.

    추가되는 컬럼: ma5, ma20, ma60, ma120, macd, macd_signal, macd_hist
    """
    df = df.copy()
    close = df["Close"]

    # 이동평균선
    df["ma5"] = close.rolling(5).mean()
    df["ma20"] = close.rolling(20).mean()
    df["ma60"] = close.rolling(60).mean()
    df["ma120"] = close.rolling(120).mean()

    # MACD (12, 26, 9)
    exp12 = close.ewm(span=12, adjust=False).mean()
    exp26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = exp12 - exp26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    return df


def render_chart(
    df: pd.DataFrame,
    symbol: str,
    name: str,
    output_path: str,
    figsize: tuple = (14, 8),
    dpi: int = 100,
) -> bool:
    """지표가 포함된 DataFrame을 3-panel 캔들차트 PNG로 렌더링한다.

    Panels: (1) 캔들 + MA, (2) 거래량, (3) MACD
    Returns: 성공 여부
    """
    if df.empty or len(df) < 5:
        logger.warning(f"[{symbol}] 데이터 부족 ({len(df)}행), 차트 생성 스킵")
        return False

    try:
        # addplot 구성: 존재하는 MA만 추가
        addplots = []
        ma_configs = [
            ("ma5", "#ef5350", 0.8),  # 빨강
            ("ma20", "#4caf50", 0.8),  # 초록
            ("ma60", "#2196f3", 0.8),  # 파랑
            ("ma120", "#ff9800", 0.8),  # 주황
        ]
        for col, color, width in ma_configs:
            if col in df.columns and df[col].notna().any():
                addplots.append(mpf.make_addplot(df[col], color=color, width=width))

        # MACD panel
        if "macd_hist" in df.columns and df["macd_hist"].notna().any():
            hist = df["macd_hist"]
            hist_pos = hist.where(hist >= 0, 0)
            hist_neg = hist.where(hist < 0, 0)
            addplots.append(mpf.make_addplot(hist_pos, type="bar", panel=2, color="#ef5350", ylabel="MACD"))
            addplots.append(mpf.make_addplot(hist_neg, type="bar", panel=2, color="#2196f3"))
            addplots.append(mpf.make_addplot(df["macd"], panel=2, color="#2196f3", width=0.8))
            addplots.append(mpf.make_addplot(df["macd_signal"], panel=2, color="#ff9800", width=0.8))

        # 스타일: 한국형 (양봉 빨강, 음봉 파랑)
        mc = mpf.make_marketcolors(
            up="#ef5350",
            down="#2196f3",
            edge="inherit",
            wick="inherit",
            volume="in",
        )
        style = mpf.make_mpf_style(
            marketcolors=mc,
            gridstyle="-",
            gridcolor="#e0e0e0",
            facecolor="white",
        )

        mpf.plot(
            df,
            type="candle",
            style=style,
            addplot=addplots if addplots else None,
            volume=True,
            volume_panel=1,
            panel_ratios=(6, 2, 2),
            figsize=figsize,
            tight_layout=True,
            title=f"{name} ({symbol})",
            savefig=dict(fname=output_path, dpi=dpi, bbox_inches="tight"),
        )

        logger.info(f"[{symbol}] 차트 저장: {output_path}")
        return True

    except Exception as e:
        logger.error(f"[{symbol}] 차트 렌더링 실패: {e}")
        return False


class BatchChartRenderer:
    """유니버스 전체 차트를 배치로 렌더링한다."""

    def __init__(self, universe_manager: UniverseManager, period: str = "8mo"):
        self.universe_manager = universe_manager
        self.period = period

    def render_all(
        self,
        output_dir: str,
        limit: Optional[int] = None,
    ) -> dict[str, bool]:
        """활성 심볼 전체에 대해 차트를 생성한다.

        Returns: {symbol: 성공여부} 딕셔너리
        """
        symbols = self.universe_manager.get_enabled_symbols()
        if limit and limit > 0:
            symbols = symbols[:limit]

        results: dict[str, bool] = {}

        for symbol in symbols:
            asset = self.universe_manager.assets.get(symbol)
            if not asset:
                results[symbol] = False
                continue

            try:
                df = yf.download(symbol, period=self.period, interval="1d", progress=False)

                # MultiIndex 컬럼 처리 (yfinance 최신 버전)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)

                if df.empty or len(df) < 5:
                    logger.warning(f"[{symbol}] 데이터 부족, 스킵")
                    results[symbol] = False
                    continue

                df = calculate_indicators(df)

                safe_name = re.sub(r'[\\/*?:"<>|\x00]', "", asset.name).replace("..", "").replace(" ", "_")
                output_path = str(Path(output_dir) / f"{safe_name}_{symbol}.png")

                results[symbol] = render_chart(df, symbol, asset.name, output_path)

            except Exception as e:
                logger.error(f"[{symbol}] 처리 실패: {e}")
                results[symbol] = False

        return results
