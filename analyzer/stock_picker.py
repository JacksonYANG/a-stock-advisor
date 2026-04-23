#!/usr/bin/env python3
"""
智能选股报告生成器
基于多维度分析，生成每日推荐股票池报告
综合: 技术面 + 资金面 + 情绪面 + 板块联动
"""

import pandas as pd
from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class PickRecommendation:
    """选股推荐"""
    code: str = ""
    name: str = ""
    score: float = 0.0
    tags: List[str] = None
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_price: float = 0.0
    position_pct: float = 20.0
    reasons: List[str] = None
    risk_level: str = "medium"

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.reasons is None:
            self.reasons = []


class StockPicker:
    """智能选股器"""

    def __init__(self):
        self.min_score = 60

    def generate_daily_report(self, top_n: int = 10) -> Dict[str, Any]:
        """生成每日选股报告"""
        from data_provider.base import DataFetcherManager
        from data_provider.sector import get_sector_fetcher

        report = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "market_summary": "",
            "recommendations": [],
            "hot_sectors": [],
            "risk_warnings": [],
        }

        # 获取强势板块
        try:
            sector_fetcher = get_sector_fetcher()
            sectors = sector_fetcher.get_all_sectors()[:5]
            report["hot_sectors"] = [s["industry"] for s in sectors]
        except:
            pass

        # 扫描自选股
        manager = DataFetcherManager()
        manager.register_sources(["baostock"])

        from config import Config
        config = Config.get()
        watch_list = config.WATCH_LIST or []

        candidates = []
        for code in watch_list:
            try:
                quote = manager.get_quote(code)
                if not quote:
                    continue

                score = 0
                tags = []
                reasons = []

                if quote.change_pct >= 9.5:
                    score += 30
                    tags.append("涨停")
                    reasons.append("涨停封板")
                elif quote.change_pct >= 5:
                    score += 20
                    tags.append("强势")
                    reasons.append("涨幅超过5%")
                elif quote.change_pct > 0:
                    score += 10
                    reasons.append("上涨")

                vol_ratio = getattr(quote, "volume_ratio", 0) or 0
                if vol_ratio > 2:
                    score += 15
                    tags.append("放量")
                    reasons.append(f"量比{vol_ratio:.1f}x")
                elif vol_ratio > 1.5:
                    score += 8
                    tags.append("温和放量")

                if hasattr(quote, "position_type"):
                    if quote.position_type == "high":
                        score += 10
                        tags.append("高位")
                        reasons.append("处于高位")
                    elif quote.position_type == "low":
                        score += 5
                        reasons.append("低位")

                if score >= self.min_score:
                    entry = quote.current_price
                    candidates.append(PickRecommendation(
                        code=code,
                        name=quote.name,
                        score=score,
                        tags=tags,
                        entry_price=entry,
                        stop_loss=entry * 0.97,
                        target_price=entry * 1.05,
                        reasons=reasons,
                        risk_level="high" if "涨停" in tags else "medium",
                    ))
            except:
                continue

        candidates.sort(key=lambda x: x.score, reverse=True)
        report["recommendations"] = candidates[:top_n]
        return report

    def print_report(self, report: Dict[str, Any]):
        """打印选股报告"""
        console.print(f"\n[bold cyan]🎯 每日智能选股报告 — {report['date']}[/bold cyan]\n")

        if report["hot_sectors"]:
            console.print(f"[bold]🔥 强势板块[/bold]: {' | '.join(report['hot_sectors'])}")

        if not report["recommendations"]:
            console.print("[yellow]今日暂无符合条件的股票[/yellow]")
            return

        table = Table(title=f"推荐股票 (共{len(report['recommendations'])}只)", show_header=True, header_style="bold magenta")
        table.add_column("代码", style="cyan")
        table.add_column("名称")
        table.add_column("评分", justify="right")
        table.add_column("标签")
        table.add_column("建议价", justify="right")
        table.add_column("止损价", justify="right")
        table.add_column("仓位", justify="right")
        table.add_column("推荐理由")

        for r in report["recommendations"]:
            risk_color = {"low": "green", "medium": "yellow", "high": "red"}.get(r.risk_level, "dim")
            tags_str = "/".join(r.tags)
            reasons_str = "; ".join(r.reasons[:2])

            table.add_row(
                r.code, r.name, f"[bold]{r.score:.0f}[/bold]",
                f"[{risk_color}]{tags_str}[/{risk_color}]",
                f"{r.entry_price:.2f}", f"{r.stop_loss:.2f}",
                f"{r.position_pct:.0f}%", reasons_str,
            )

        console.print(table)


_picker = None


def get_stock_picker() -> StockPicker:
    global _picker
    if _picker is None:
        _picker = StockPicker()
    return _picker
