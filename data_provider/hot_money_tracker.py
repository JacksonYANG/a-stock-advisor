#!/usr/bin/env python3
"""
游资席位追踪器
基于 AKShare 东方财富龙虎榜接口，追踪知名游资动向
"""

import yaml
import pandas as pd
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

# AKShare 龙虎榜接口
try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False


@dataclass
class HotMoneyActivity:
    """游资活动记录"""
    date: str = ""
    group_name: str = ""       # 游资名称 (如 "佛山系")
    seat_name: str = ""        # 营业部全名
    stock_code: str = ""       # 操作股票代码
    stock_name: str = ""       # 操作股票名称
    buy_amount: float = 0.0    # 买入金额(万)
    sell_amount: float = 0.0   # 卖出金额(万)
    net_amount: float = 0.0    # 净额(万)
    style: str = ""            # 操作风格


class HotMoneyTracker:
    """游资追踪器"""

    def __init__(self):
        self._registry: Dict[str, Dict] = {}
        self._seat_to_group: Dict[str, str] = {}  # seat_name -> group_name
        self._load_registry()

    def _load_registry(self):
        """加载席位注册表"""
        registry_path = Path(__file__).parent.parent / "data" / "seat_registry.yaml"
        if not registry_path.exists():
            return

        with open(registry_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        seats = data.get("seats", {})
        for group_name, group_data in seats.items():
            self._registry[group_name] = group_data
            for seat in group_data.get("seats", []):
                self._seat_to_group[seat] = group_name

    def _match_group(self, seat_name: str) -> Optional[str]:
        """根据营业部名称匹配游资组"""
        # 精确匹配
        if seat_name in self._seat_to_group:
            return self._seat_to_group[seat_name]

        # 模糊匹配 (包含关键部分)
        for known_seat, group in self._seat_to_group.items():
            # 去掉"证券营业部"后缀匹配
            clean_known = known_seat.replace("证券营业部", "").replace("证券分公司", "")
            clean_seat = seat_name.replace("证券营业部", "").replace("证券分公司", "")
            if clean_known in clean_seat or clean_seat in clean_known:
                return group

        return None

    def get_daily_activities(self, date: Optional[str] = None) -> List[HotMoneyActivity]:
        """获取每日游资活动"""
        if not HAS_AKSHARE:
            return []

        if date is None:
            date = datetime.now().strftime("%Y%m%d")

        try:
            # 获取活跃营业部数据
            df = ak.stock_lhb_hyyyb_em(date=date)
            if df is None or df.empty:
                return []

            results = []
            for _, row in df.iterrows():
                seat_name = str(row.get("营业部名称", ""))
                group_name = self._match_group(seat_name)

                if group_name:
                    group_data = self._registry.get(group_name, {})
                    results.append(HotMoneyActivity(
                        date=date,
                        group_name=group_name,
                        seat_name=seat_name,
                        stock_code=str(row.get("股票代码", "")),
                        stock_name=str(row.get("股票名称", "")),
                        buy_amount=float(row.get("买入额", 0)) / 1e4,
                        sell_amount=float(row.get("卖出额", 0)) / 1e4,
                        net_amount=float(row.get("净额", 0)) / 1e4,
                        style=group_data.get("style", ""),
                    ))

            return results
        except Exception:
            return []

    def get_group_summary(self, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """按游资组汇总"""
        activities = self.get_daily_activities(date)

        summary: Dict[str, Dict] = {}
        for a in activities:
            if a.group_name not in summary:
                summary[a.group_name] = {
                    "group_name": a.group_name,
                    "style": a.style,
                    "buy_total": 0.0,
                    "sell_total": 0.0,
                    "net_total": 0.0,
                    "stocks": [],
                    "seats": set(),
                }
            summary[a.group_name]["buy_total"] += a.buy_amount
            summary[a.group_name]["sell_total"] += a.sell_amount
            summary[a.group_name]["net_total"] += a.net_amount
            summary[a.group_name]["stocks"].append(f"{a.stock_name}({a.stock_code})")
            summary[a.group_name]["seats"].add(a.seat_name)

        result = []
        for s in summary.values():
            s["seats"] = list(s["seats"])
            s["stock_count"] = len(set(s["stocks"]))
            result.append(s)

        result.sort(key=lambda x: x["net_total"], reverse=True)
        return result

    def track_stock(self, code: str, days: int = 30) -> List[HotMoneyActivity]:
        """追踪某只股票最近N天的游资参与情况"""
        if not HAS_AKSHARE:
            return []

        results = []
        today = datetime.now()

        for i in range(days):
            d = today - timedelta(days=i)
            date_str = d.strftime("%Y%m%d")

            try:
                df = ak.stock_lhb_hyyyb_em(date=date_str)
                if df is None or df.empty:
                    continue

                for _, row in df.iterrows():
                    stock_code = str(row.get("股票代码", ""))
                    if stock_code != code:
                        continue

                    seat_name = str(row.get("营业部名称", ""))
                    group_name = self._match_group(seat_name)

                    if group_name:
                        group_data = self._registry.get(group_name, {})
                        results.append(HotMoneyActivity(
                            date=date_str,
                            group_name=group_name,
                            seat_name=seat_name,
                            stock_code=code,
                            stock_name=str(row.get("股票名称", "")),
                            buy_amount=float(row.get("买入额", 0)) / 1e4,
                            sell_amount=float(row.get("卖出额", 0)) / 1e4,
                            net_amount=float(row.get("净额", 0)) / 1e4,
                            style=group_data.get("style", ""),
                        ))
            except:
                continue

        return results

    def list_known_groups(self) -> List[Dict[str, Any]]:
        """列出所有已注册的游资组"""
        results = []
        for name, data in self._registry.items():
            results.append({
                "name": name,
                "aliases": data.get("aliases", []),
                "style": data.get("style", ""),
                "seat_count": len(data.get("seats", [])),
                "seats": data.get("seats", []),
            })
        return results


_tracker = None


def get_hot_money_tracker() -> HotMoneyTracker:
    global _tracker
    if _tracker is None:
        _tracker = HotMoneyTracker()
    return _tracker
