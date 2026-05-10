#!/usr/bin/env python3
"""
盘中实时监控脚本
在交易时间段内持续监控自选股异动，触发预警时推送 Telegram
用法: python run_monitoring.py [--interval 60]
"""

import sys
import os
import time
import argparse
import threading
from pathlib import Path
from datetime import datetime, time as dtime

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from data_provider.base import DataFetcherManager
from analyzer.alert_system import get_alert_system, Alert, AlertType
from analyzer.telegram_notifier import TelegramNotifier
from utils.trading_calendar import is_trading_day as calendar_is_trading_day

# 交易时间段
TRADING_MORNING_START = dtime(9, 25)
TRADING_MORNING_END   = dtime(11, 35)
TRADING_AFTERNOON_START = dtime(12, 55)
TRADING_AFTERNOON_END   = dtime(15, 5)


def is_in_trading_time() -> bool:
    """检查当前是否在交易时间内（去掉开盘前9:20-9:25和午休11:35-12:55）"""
    now = datetime.now()
    current = now.time()

    # Use proper trading calendar
    if not calendar_is_trading_day():
        return False

    morning = TRADING_MORNING_START <= current <= TRADING_MORNING_END
    afternoon = TRADING_AFTERNOON_START <= current <= TRADING_AFTERNOON_END
    return morning or afternoon


def alert_callback(alert: Alert):
    """预警触发时的回调（打印到控制台）"""
    print(f"[ALERT] {alert.alert_type.value} | {alert.code} {alert.name} | "
          f"价格:{alert.current_price:.2f} ({alert.change_pct:+.2f}%) | {alert.message}")


def run_monitoring(interval: int = 60):
    """
    盘中监控主循环
    - 检查是否在交易时间内
    - 在交易时间内的每个interval秒检查一次异动
    - 触发预警时通过 callback 发送到 Telegram（不再调用 send_alerts）
    """
    config = Config.get()
    codes = config.WATCH_LIST

    if not codes:
        print("⚠ 未配置自选股 (WATCH_LIST)，监控退出")
        return

    print(f"📡 盘中监控启动 | 自选股: {len(codes)} 只 | 轮询间隔: {interval}秒")
    print(f"   交易时间段: 9:25-11:35 / 12:55-15:05 (交易日)")
    print(f"   预警将发送至 Telegram (severity: warning/danger)")
    print("-" * 50)

    # 初始化组件
    alert_system = get_alert_system()

    # 回调1: 控制台打印
    alert_system.register_callback(alert_callback)

    # 回调2: Telegram 发送（这是唯一的 TG 发送路径，不再有 send_alerts 的重复发送）
    notifier = TelegramNotifier()

    def tg_callback(alert: Alert):
        if alert.severity in ("warning", "danger"):
            try:
                msg = alert.to_telegram_msg()
                notifier.send_message(msg)
            except Exception as e:
                print(f"   [TG错误] {e}")
    alert_system.register_callback(tg_callback)

    # 注册摘要回调（每2小时发送一次预警摘要）
    def summary_callback(summary_text: str):
        try:
            notifier.send_message(summary_text)
            print(f"[摘要] 已发送预警摘要")
        except Exception as e:
            print(f"   [摘要TG错误] {e}")
    alert_system.register_summary_callback(summary_callback)

    cycle = 0
    last_summary_time = datetime.now()

    while True:
        now = datetime.now()
        current_time = now.time()

        # 非交易日
        if not calendar_is_trading_day():
            if cycle == 0:
                print(f"[{now.strftime('%H:%M:%S')}] 非交易日，监控暂停")
            time.sleep(60)
            cycle = (cycle + 1) % 10
            continue

        in_morning = TRADING_MORNING_START <= current_time <= TRADING_MORNING_END
        in_afternoon = TRADING_AFTERNOON_START <= current_time <= TRADING_AFTERNOON_END

        if not (in_morning or in_afternoon):
            if cycle == 0:
                print(f"[{now.strftime('%H:%M:%S')}] 非交易时间段，监控暂停")
            time.sleep(30)
            cycle = (cycle + 1) % 10
            continue

        # === 交易时间内，执行监控 ===
        if cycle % 5 == 0:  # 每5个interval打印一次状态
            print(f"[{now.strftime('%H:%M:%S')}] 盘中监控中... ({len(codes)} 只自选股)")

        # 每30分钟发送一次市场情绪摘要
        if (now - last_summary_time).total_seconds() >= 1800:
            try:
                from analyzer.market_sentiment import get_sentiment_analyzer
                sentiment = get_sentiment_analyzer().get_sentiment()
                summary = f"📊 {now.strftime('%H:%M')} 市场情绪\n" \
                          f"涨停: {sentiment.limit_up_count} | 跌停: {sentiment.limit_down_count}\n" \
                          f"情绪: {sentiment.sentiment_label} ({sentiment.sentiment_score:.0f}/100)"
                notifier.send_message(summary)
                print(f"   [情绪摘要] {sentiment.sentiment_label} {sentiment.sentiment_score:.0f}/100")
                last_summary_time = now
            except Exception as e:
                print(f"   [情绪摘要失败] {e}")

        # 逐个检查异动
        alert_count = 0
        for code in codes:
            try:
                code = code.strip().zfill(6)
                alerts = alert_system.check_and_alert(code)
                if alerts:
                    alert_count += len(alerts)
                    # FIX: 不再调用 send_alerts()，因为 tg_callback 已在 check_and_alert
                    # 触发时通过回调处理 Telegram 发送。
                    # 但 check_and_alert 本身只返回 alerts，不触发回调。
                    # 所以我们仍然需要 send_alerts 来触发回调（打印+TG）。
                    alert_system.send_alerts(alerts)
            except Exception as e:
                print(f"   [检查 {code} 失败] {e}")

        if alert_count > 0:
            print(f"[{now.strftime('%H:%M:%S')}] 触发 {alert_count} 个预警")

        # 每2小时发送一次预警摘要
        alert_system.maybe_send_summary(interval_hours=2)

        time.sleep(interval)
        cycle = (cycle + 1) % 100


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="盘中实时监控")
    parser.add_argument("--interval", "-i", type=int, default=60,
                        help="轮询间隔（秒），默认60")
    args = parser.parse_args()

    if not calendar_is_trading_day():
        print("今天不是交易日，监控不启动")
    else:
        run_monitoring(interval=args.interval)
