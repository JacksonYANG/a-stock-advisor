#!/usr/bin/env python3
"""
A股分析系统 Web 控制台
基于 Flask，提供可视化仪表盘
"""

import os
import json
from datetime import datetime
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
app.template_folder = "templates"

os.makedirs("reports/charts", exist_ok=True)
os.makedirs("templates", exist_ok=True)


@app.route("/")
def index():
    """仪表盘主页"""
    return render_template("dashboard.html")


@app.route("/api/market")
def api_market():
    """市场总览API"""
    try:
        from data_provider.base import DataFetcherManager
        manager = DataFetcherManager()
        manager.register_sources(["baostock"])

        sh = manager.get_quote("000001")
        cy = manager.get_quote("399006")

        return jsonify({
            "success": True,
            "data": {
                "shanghai": {"price": sh.current_price if sh else 0, "change": sh.change_pct if sh else 0},
                "chengye": {"price": cy.current_price if cy else 0, "change": cy.change_pct if cy else 0},
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/sector")
def api_sector():
    """板块数据API"""
    try:
        from data_provider.sector import get_sector_fetcher
        fetcher = get_sector_fetcher()
        sectors = fetcher.get_all_sectors()[:10]
        return jsonify({"success": True, "data": sectors})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/portfolio")
def api_portfolio():
    """持仓数据API"""
    try:
        from data_provider.storage import Database
        db = Database()
        positions = db.get_positions()
        return jsonify({
            "success": True,
            "data": [
                {
                    "code": p.code, "name": p.name, "shares": p.shares,
                    "avg_cost": p.avg_cost, "current_price": p.current_price,
                    "market_value": p.market_value, "floating_pnl": p.floating_pnl,
                }
                for p in positions
            ]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    """回测API"""
    try:
        data = request.json
        code = data.get("code", "000001")
        start = data.get("start", "2025-01-01")

        from analyzer.backtest_engine import get_backtest_engine
        engine = get_backtest_engine()
        result = engine.run(code, start)

        return jsonify({
            "success": True,
            "data": {
                "total_return": result.total_return,
                "annualized_return": result.annualized_return,
                "win_rate": result.win_rate,
                "max_drawdown": result.max_drawdown,
                "sharpe_ratio": result.sharpe_ratio,
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    print("🌐 启动 Web 控制台: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
