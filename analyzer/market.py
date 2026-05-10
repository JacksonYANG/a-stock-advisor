"""
市场总览分析模块
获取大盘指数、板块涨跌、市场情绪等
"""

import pandas as pd
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from rich.console import Console

console = Console()


@dataclass
class IndexData:
    """指数数据"""
    code: str
    name: str
    price: float
    change_pct: float
    volume: float = 0
    amount: float = 0


@dataclass
class SectorData:
    """板块数据"""
    name: str
    change_pct: float
    lead_stock: str = ""
    lead_stock_change: float = 0.0


@dataclass
class MarketOverview:
    """市场总览"""
    indices: Dict[str, IndexData] = field(default_factory=dict)
    top_sectors: List[SectorData] = field(default_factory=list)
    bottom_sectors: List[SectorData] = field(default_factory=list)
    up_count: int = 0
    down_count: int = 0
    flat_count: int = 0
    limit_up_count: int = 0
    limit_down_count: int = 0
    total_amount: float = 0.0

    def to_summary(self) -> str:
        """生成市场总览摘要"""
        lines = ["📋 A股市场总览", "=" * 50]

        # 指数
        lines.append("\n📊 大盘指数:")
        for name, idx in self.indices.items():
            arrow = "🔴" if idx.change_pct < 0 else "🟢" if idx.change_pct > 0 else "⚪"
            lines.append(f"  {arrow} {idx.name}: {idx.price:.2f} ({idx.change_pct:+.2f}%)")

        # 涨跌统计
        total = self.up_count + self.down_count + self.flat_count
        lines.append(f"\n📈 涨跌统计:")
        lines.append(f"  上涨: {self.up_count}  下跌: {self.down_count}  平盘: {self.flat_count}")
        lines.append(f"  涨停: {self.limit_up_count}  跌停: {self.limit_down_count}")
        if total > 0:
            lines.append(f"  上涨占比: {self.up_count/total:.1%}")

        # 成交额
        if self.total_amount > 0:
            lines.append(f"\n💰 两市成交额: {self.total_amount/1e8:.0f}亿元")

        # 领涨板块
        if self.top_sectors:
            lines.append("\n🔥 领涨板块:")
            for s in self.top_sectors[:5]:
                lines.append(f"  🟢 {s.name}: {s.change_pct:+.2f}% (领涨: {s.lead_stock} {s.lead_stock_change:+.2f}%)")

        # 领跌板块
        if self.bottom_sectors:
            lines.append("\n❄️ 领跌板块:")
            for s in self.bottom_sectors[:5]:
                lines.append(f"  🔴 {s.name}: {s.change_pct:+.2f}%")

        return "\n".join(lines)


class MarketAnalyzer:
    """市场分析器"""

    # 主要指数代码
    INDEX_CODES = {
        "上证指数": "000001",
        "深证成指": "399001",
        "创业板指": "399006",
        "科创50": "000688",
        "沪深300": "000300",
        "中证500": "000905",
    }

    def get_indices(self) -> Dict[str, IndexData]:
        """获取主要指数数据"""
        indices = {}
        try:
            import akshare as ak
            df = ak.stock_zh_index_spot_em()

            for name, code in self.INDEX_CODES.items():
                try:
                    row = df[df["代码"] == code]
                    if not row.empty:
                        r = row.iloc[0]
                        indices[name] = IndexData(
                            code=code,
                            name=name,
                            price=float(r.get("最新价", 0) or 0),
                            change_pct=float(r.get("涨跌幅", 0) or 0),
                        )
                except Exception:
                    pass

        except Exception as e:
            console.print(f"[yellow]⚠ 获取指数数据失败: {e}[/yellow]")

        return indices

    def get_market_stats(self) -> Dict[str, int]:
        """获取涨跌统计"""
        stats = {"up": 0, "down": 0, "flat": 0, "limit_up": 0, "limit_down": 0}
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()

            if df is not None and not df.empty:
                changes = df["涨跌幅"].dropna()
                stats["up"] = int((changes > 0).sum())
                stats["down"] = int((changes < 0).sum())
                stats["flat"] = int((changes == 0).sum())
                stats["limit_up"] = int((changes >= 9.9).sum())
                stats["limit_down"] = int((changes <= -9.9).sum())

        except Exception as e:
            console.print(f"[yellow]⚠ 获取涨跌统计失败: {e}[/yellow]")

        return stats

    def get_sector_ranking(self) -> tuple[list[SectorData], list[SectorData]]:
        """获取板块涨跌排名"""
        top_sectors = []
        bottom_sectors = []

        try:
            import akshare as ak
            # 概念板块
            df = ak.stock_board_concept_name_em()

            if df is not None and not df.empty:
                df = df.sort_values("涨跌幅", ascending=False)

                for _, row in df.head(5).iterrows():
                    top_sectors.append(SectorData(
                        name=str(row.get("板块名称", "")),
                        change_pct=float(row.get("涨跌幅", 0) or 0),
                        lead_stock=str(row.get("领涨股票", "")),
                        lead_stock_change=float(row.get("领涨股票涨跌幅", 0) or 0),
                    ))

                for _, row in df.tail(5).iterrows():
                    bottom_sectors.append(SectorData(
                        name=str(row.get("板块名称", "")),
                        change_pct=float(row.get("涨跌幅", 0) or 0),
                    ))

        except Exception as e:
            console.print(f"[yellow]⚠ 获取板块数据失败: {e}[/yellow]")

        return top_sectors, bottom_sectors

    def get_overview(self) -> MarketOverview:
        """获取完整市场总览"""
        overview = MarketOverview()

        console.print("[dim]正在获取大盘指数...[/dim]")
        overview.indices = self.get_indices()

        console.print("[dim]正在统计涨跌家数...[/dim]")
        stats = self.get_market_stats()
        overview.up_count = stats["up"]
        overview.down_count = stats["down"]
        overview.flat_count = stats["flat"]
        overview.limit_up_count = stats["limit_up"]
        overview.limit_down_count = stats["limit_down"]

        console.print("[dim]正在获取板块排名...[/dim]")
        top, bottom = self.get_sector_ranking()
        overview.top_sectors = top
        overview.bottom_sectors = bottom

        return overview
