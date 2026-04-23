#!/usr/bin/env python3
"""
PDF 分析报告生成器
生成每日/每周分析报告 PDF
"""

import os
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

try:
    from fpdf import FPDF
    HAS_FPDF = True
except ImportError:
    HAS_FPDF = False


class StockReportPDF(FPDF):
    """A股分析报告 PDF"""

    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 10, "A-Stock Advisor Report", 0, 1, "C")
        self.set_font("Helvetica", "", 10)
        self.cell(0, 5, datetime.now().strftime("%Y-%m-%d"), 0, 1, "C")
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", 0, 0, "C")

    def add_section(self, title: str, content: str):
        """添加章节"""
        self.set_font("Helvetica", "B", 12)
        self.cell(0, 10, title, 0, 1)
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 6, content)
        self.ln(5)

    def add_table(self, headers: List[str], rows: List[List[str]]):
        """添加表格"""
        col_width = (self.w - 20) / len(headers)
        
        # 表头
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(60, 60, 60)
        self.set_text_color(255, 255, 255)
        for h in headers:
            self.cell(col_width, 8, h, 1, 0, "C", True)
        self.ln()

        # 数据行
        self.set_font("Helvetica", "", 8)
        self.set_text_color(0, 0, 0)
        fill = False
        for row in rows:
            if fill:
                self.set_fill_color(240, 240, 240)
            else:
                self.set_fill_color(255, 255, 255)
            for cell in row:
                self.cell(col_width, 7, str(cell), 1, 0, "C", True)
            self.ln()
            fill = not fill


class ReportGenerator:
    """报告生成器"""

    def __init__(self, output_dir: str = "reports"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_daily_report(self, watch_list: List[str] = None) -> Optional[str]:
        """生成每日分析报告"""
        if not HAS_FPDF:
            return None

        pdf = StockReportPDF()
        pdf.add_page()

        # 1. 市场概览
        try:
            from data_provider.base import DataFetcherManager
            from config import Config

            config = Config.get()
            codes = watch_list or config.WATCH_LIST

            manager = DataFetcherManager()
            manager.register_sources(["baostock"])

            market_summary = []
            stock_rows = []

            for code in codes[:15]:
                try:
                    quote = manager.get_quote(code)
                    if quote:
                        chg = f"+{quote.change_pct:.2f}%" if quote.change_pct > 0 else f"{quote.change_pct:.2f}%"
                        stock_rows.append([code, quote.name, f"{quote.price:.2f}", chg])
                except:
                    stock_rows.append([code, "N/A", "N/A", "N/A"])

            pdf.add_section("Market Summary", f"Tracking {len(codes)} stocks on {datetime.now().strftime('%Y-%m-%d')}")
            
            if stock_rows:
                pdf.add_table(["Code", "Name", "Price", "Change%"], stock_rows)

        except Exception as e:
            pdf.add_section("Market Summary", f"Error: {str(e)}")

        # 2. 持仓
        try:
            from data_provider.storage import Database
            db = Database()
            positions = db.get_positions()

            if positions:
                pdf.add_section("Portfolio", f"Total positions: {len(positions)}")
                pos_rows = []
                for p in positions:
                    pnl = p.floating_pnl or 0
                    pnl_str = f"+{pnl:.2f}" if pnl > 0 else f"{pnl:.2f}"
                    pos_rows.append([p.code, p.name, str(p.shares), f"{p.avg_cost:.2f}", pnl_str])
                pdf.add_table(["Code", "Name", "Shares", "AvgCost", "PnL"], pos_rows)
            else:
                pdf.add_section("Portfolio", "No positions")
        except:
            pass

        # 3. 策略信号
        try:
            from analyzer.strategy_engine import get_strategy_engine
            engine = get_strategy_engine()
            strategies = engine.list_strategies()
            pdf.add_section("Active Strategies", f"Total: {len(strategies)} strategies loaded")
        except:
            pass

        # 保存
        filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        filepath = os.path.join(self.output_dir, filename)
        pdf.output(filepath)
        return filepath


_report_gen = None


def get_report_generator() -> ReportGenerator:
    global _report_gen
    if _report_gen is None:
        _report_gen = ReportGenerator()
    return _report_gen
