"""
评分历史记录模块
保存每个阶段的评分，用于检测评分突变（delta >= 15 等）
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple

from config import Config


SCORE_HISTORY_FILE = Path(__file__).parent.parent / "data" / "score_history.json"


def _load_history() -> dict:
    """加载评分历史"""
    if SCORE_HISTORY_FILE.exists():
        try:
            with open(SCORE_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _save_history(history: dict):
    """保存评分历史"""
    SCORE_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SCORE_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def save_scores(phase: str, scores: Dict[str, int]):
    """
    保存某个阶段的评分

    Args:
        phase: pre_market / mid_day / after_close
        scores: {code: score} 映射
    """
    history = _load_history()
    today = datetime.now().strftime("%Y-%m-%d")

    if today not in history:
        history[today] = {}

    history[today][phase] = scores

    # 只保留最近 7 天的数据
    keys = sorted(history.keys())
    if len(keys) > 7:
        for k in keys[:-7]:
            del history[k]

    _save_history(history)


def get_previous_scores(phase: str) -> Dict[str, int]:
    """
    获取当前阶段的上一次评分（可能是今天的前一个阶段，也可能是昨天的）

    Returns:
        {code: score} 映射，可能为空
    """
    history = _load_history()
    today = datetime.now().strftime("%Y-%m-%d")

    phase_order = ["pre_market", "mid_day", "after_close"]
    current_idx = phase_order.index(phase) if phase in phase_order else -1

    # 先看今天有没有前一个阶段的数据
    if today in history:
        today_data = history[today]
        # 尝试获取当前阶段的前一个阶段
        if current_idx > 0:
            prev_phase = phase_order[current_idx - 1]
            if prev_phase in today_data:
                return today_data[prev_phase]

    # 回退到昨天最后一个阶段
    yesterday = None
    for date_key in sorted(history.keys(), reverse=True):
        if date_key < today:
            yesterday = date_key
            break

    if yesterday and yesterday in history:
        yesterday_data = history[yesterday]
        # 优先取 after_close，然后 mid_day
        for p in reversed(phase_order):
            if p in yesterday_data:
                return yesterday_data[p]

    return {}


def get_score_delta(current_scores: Dict[str, int], previous_scores: Dict[str, int]) -> Dict[str, int]:
    """
    计算评分变化量

    Returns:
        {code: delta} 其中 delta = current - previous
    """
    deltas = {}
    for code, score in current_scores.items():
        if code in previous_scores:
            deltas[code] = score - previous_scores[code]
    return deltas
