"""
数据可视化模块
生成K线图 + 技术指标图表
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")  # 无头模式
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch
from pathlib import Path
from typing import Optional
from datetime import datetime

# 支持中文
plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei", "WenQuanYi Micro Hei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


class ChartGenerator:
    """图表生成器"""

    def __init__(self, output_dir: str = "reports/charts"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def cleanup_old_charts(self, max_age_days: int = 7):
        """Delete chart files older than max_age_days."""
        import time

        if not self.output_dir.exists():
            return

        now = time.time()
        cutoff = now - max_age_days * 86400  # seconds in a day

        for f in self.output_dir.iterdir():
            if f.is_file() and f.suffix in (".png", ".jpg", ".webp"):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                except OSError:
                    pass

    def plot_kline_with_indicators(
        self,
        df: pd.DataFrame,
        code: str = "",
        name: str = "",
        buy_score: int = 50,
        operation: str = "",
        save_path: Optional[str] = None,
    ) -> str:
        """
        生成 K线 + 技术指标图

        Args:
            df: K线数据 (columns: date, open, high, low, close, volume)
            code: 股票代码
            name: 股票名称
            buy_score: 综合评分
            operation: 操作建议

        Returns:
            保存的图片路径
        """
        if df is None or len(df) < 5:
            return ""

        self.cleanup_old_charts()

        fig, axes = plt.subplots(4, 1, figsize=(16, 12), height_ratios=[3, 1, 1, 1])
        fig.suptitle(f"{code} {name} - 技术分析 (评分:{buy_score} {operation})", fontsize=14, fontweight="bold")

        dates = df["date"] if "date" in df.columns else range(len(df))
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        # ===== 1. K线图 + 均线 + 布林带 =====
        ax1 = axes[0]

        # 绘制K线 (简化版，用收盘价折线 + 填充色)
        colors = ["red" if df["close"].iloc[i] >= df["open"].iloc[i] else "green"
                   for i in range(len(df))]

        for i in range(len(df)):
            o, c = df["open"].iloc[i], df["close"].iloc[i]
            h, l = df["high"].iloc[i], df["low"].iloc[i]
            color = colors[i]
            ax1.plot([i, i], [l, h], color=color, linewidth=0.8)
            ax1.plot([i, i], [min(o, c), max(o, c)], color=color, linewidth=3)

        # 均线
        if len(close) >= 5:
            ma5 = close.rolling(5).mean()
            ma10 = close.rolling(10).mean()
            ma20 = close.rolling(20).mean()
            ax1.plot(ma5.index, ma5.values, label="MA5", color="#FF6B6B", linewidth=1, alpha=0.8)
            ax1.plot(ma10.index, ma10.values, label="MA10", color="#4ECDC4", linewidth=1, alpha=0.8)
            ax1.plot(ma20.index, ma20.values, label="MA20", color="#45B7D1", linewidth=1, alpha=0.8)

        # 布林带
        if len(close) >= 20:
            ma20 = close.rolling(20).mean()
            std20 = close.rolling(20).std()
            upper = ma20 + 2 * std20
            lower = ma20 - 2 * std20
            ax1.fill_between(upper.index, upper.values, lower.values, alpha=0.1, color="blue")
            ax1.plot(upper.index, upper.values, "--", color="blue", alpha=0.3, linewidth=0.8)
            ax1.plot(lower.index, lower.values, "--", color="blue", alpha=0.3, linewidth=0.8)

        ax1.legend(loc="upper left", fontsize=8)
        ax1.set_ylabel("价格")
        ax1.grid(True, alpha=0.3)
        ax1.set_xticklabels([])

        # ===== 2. 成交量 =====
        ax2 = axes[1]
        vol_colors = ["red" if df["close"].iloc[i] >= df["open"].iloc[i] else "green"
                       for i in range(len(df))]
        ax2.bar(range(len(volume)), volume, color=vol_colors, alpha=0.7, width=0.8)
        if len(volume) >= 5:
            vol_ma5 = volume.rolling(5).mean()
            ax2.plot(vol_ma5.index, vol_ma5.values, color="orange", linewidth=1, label="VOL MA5")
            ax2.legend(loc="upper left", fontsize=8)
        ax2.set_ylabel("成交量")
        ax2.grid(True, alpha=0.3)
        ax2.set_xticklabels([])

        # ===== 3. MACD =====
        ax3 = axes[2]
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd_bar = 2 * (dif - dea)

        ax3.plot(dif.index, dif.values, label="DIF", color="red", linewidth=1)
        ax3.plot(dea.index, dea.values, label="DEA", color="blue", linewidth=1)
        bar_colors = ["red" if v >= 0 else "green" for v in macd_bar.values]
        ax3.bar(macd_bar.index, macd_bar.values, color=bar_colors, alpha=0.6, width=0.8)
        ax3.axhline(y=0, color="gray", linewidth=0.5)
        ax3.legend(loc="upper left", fontsize=8)
        ax3.set_ylabel("MACD")
        ax3.grid(True, alpha=0.3)
        ax3.set_xticklabels([])

        # ===== 4. RSI =====
        ax4 = axes[3]
        delta = close.diff()
        for period, color, label in [(6, "red", "RSI6"), (12, "blue", "RSI12"), (24, "green", "RSI24")]:
            gain = delta.where(delta > 0, 0).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss.replace(0, np.inf)
            rsi = 100 - (100 / (1 + rs))
            ax4.plot(rsi.index, rsi.values, label=label, color=color, linewidth=1)

        ax4.axhline(y=70, color="red", linewidth=0.5, linestyle="--", alpha=0.5)
        ax4.axhline(y=30, color="green", linewidth=0.5, linestyle="--", alpha=0.5)
        ax4.axhline(y=50, color="gray", linewidth=0.5, linestyle="--", alpha=0.3)
        ax4.set_ylabel("RSI")
        ax4.set_ylim(0, 100)
        ax4.legend(loc="upper left", fontsize=8)
        ax4.grid(True, alpha=0.3)

        # 设置 x 轴
        n_ticks = min(10, len(df))
        tick_positions = np.linspace(0, len(df) - 1, n_ticks, dtype=int)
        if "date" in df.columns:
            tick_labels = [pd.to_datetime(df["date"].iloc[i]).strftime("%m-%d") for i in tick_positions]
        else:
            tick_labels = [str(i) for i in tick_positions]
        ax4.set_xticks(tick_positions)
        ax4.set_xticklabels(tick_labels, rotation=45, fontsize=8)

        plt.tight_layout()

        if save_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = str(self.output_dir / f"{code}_{timestamp}.png")

        plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="white")
        plt.close()

        return save_path

    def plot_market_overview(
        self,
        overview,  # MarketOverview
        save_path: Optional[str] = None,
    ) -> str:
        """生成市场总览图"""
        self.cleanup_old_charts()

        fig, axes = plt.subplots(2, 2, figsize=(14, 8))
        fig.suptitle("A股市场总览", fontsize=16, fontweight="bold")

        # 1. 指数涨跌
        ax1 = axes[0, 0]
        if overview.indices:
            names = list(overview.indices.keys())
            changes = [idx.change_pct for idx in overview.indices.values()]
            colors = ["red" if c > 0 else "green" if c < 0 else "gray" for c in changes]
            bars = ax1.barh(names, changes, color=colors)
            ax1.set_title("主要指数涨跌幅(%)")
            ax1.axvline(x=0, color="gray", linewidth=0.5)

        # 2. 涨跌家数饼图
        ax2 = axes[0, 1]
        if overview.up_count + overview.down_count + overview.flat_count > 0:
            sizes = [overview.up_count, overview.down_count, overview.flat_count]
            labels = [f"上涨({overview.up_count})", f"下跌({overview.down_count})", f"平盘({overview.flat_count})"]
            colors = ["red", "green", "gray"]
            ax2.pie(sizes, labels=labels, colors=colors, autopct="%1.1f%%", startangle=90)
            ax2.set_title("涨跌分布")

        # 3. 领涨板块
        ax3 = axes[1, 0]
        if overview.top_sectors:
            names = [s.name for s in overview.top_sectors[:8]]
            changes = [s.change_pct for s in overview.top_sectors[:8]]
            ax3.barh(names, changes, color="red", alpha=0.7)
            ax3.set_title("领涨板块(%)")
            ax3.axvline(x=0, color="gray", linewidth=0.5)

        # 4. 领跌板块
        ax4 = axes[1, 1]
        if overview.bottom_sectors:
            names = [s.name for s in overview.bottom_sectors[:8]]
            changes = [s.change_pct for s in overview.bottom_sectors[:8]]
            ax4.barh(names, changes, color="green", alpha=0.7)
            ax4.set_title("领跌板块(%)")
            ax4.axvline(x=0, color="gray", linewidth=0.5)

        plt.tight_layout()

        if save_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = str(self.output_dir / f"market_{timestamp}.png")

        plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="white")
        plt.close()

        return save_path
