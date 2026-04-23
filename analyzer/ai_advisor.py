"""
AI 决策辅助模块
支持 DeepSeek / OpenAI / Ollama 等多种 LLM
基于技术分析结果 + 新闻资讯，生成智能投资建议
"""

import json
from typing import Optional
from dataclasses import dataclass
from rich.console import Console

from config import Config
from analyzer.technical import TechnicalResult

console = Console()


@dataclass
class AIAdvice:
    """AI 分析建议"""
    summary: str = ""           # 核心结论
    operation: str = "观望"     # 操作建议
    entry_price: float = 0.0    # 建议买入价
    stop_loss: float = 0.0      # 止损价
    target_price: float = 0.0   # 目标价
    risk_level: str = "中"      # 风险等级: 低/中/高
    key_factors: list = None    # 关键因素
    risk_warnings: list = None  # 风险提示
    strategy: str = ""          # 建议策略

    def __post_init__(self):
        self.key_factors = self.key_factors or []
        self.risk_warnings = self.risk_warnings or []

    def to_markdown(self) -> str:
        lines = [
            "🤖 AI 智能分析",
            "=" * 50,
            f"📌 核心结论: {self.summary}",
            f"📋 操作建议: {self.operation}",
            f"⚠️ 风险等级: {self.risk_level}",
        ]
        if self.entry_price:
            lines.append(f"💰 建议买入价: {self.entry_price:.2f}")
        if self.stop_loss:
            lines.append(f"🛑 止损价: {self.stop_loss:.2f}")
        if self.target_price:
            lines.append(f"🎯 目标价: {self.target_price:.2f}")
        if self.strategy:
            lines.append(f"📊 策略: {self.strategy}")

        if self.key_factors:
            lines.append("\n✅ 关键看多因素:")
            for f in self.key_factors:
                lines.append(f"  • {f}")

        if self.risk_warnings:
            lines.append("\n⚠️ 风险提示:")
            for f in self.risk_warnings:
                lines.append(f"  • {f}")

        return "\n".join(lines)


class AIAdvisor:
    """AI 决策顾问"""

    def __init__(self):
        self.config = Config.get()

    @property
    def is_available(self) -> bool:
        return self.config.has_llm

    def _build_prompt(self, tech: TechnicalResult) -> str:
        """构建分析提示词"""
        return f"""你是一位专业的A股投资分析师。请根据以下技术分析数据，给出投资建议。

## 股票信息
- 代码: {tech.code}
- 名称: {tech.name}
- 当前价格: {tech.current_price:.2f}

## 技术指标
- 均线趋势: {tech.trend_status.value} (MA5={tech.ma5:.2f}, MA10={tech.ma10:.2f}, MA20={tech.ma20:.2f}, MA60={tech.ma60:.2f})
- MACD: {tech.macd_status.value} (DIF={tech.dif:.4f}, DEA={tech.dea:.4f}, BAR={tech.macd_bar:.4f})
- RSI: {tech.rsi_status.value} (RSI6={tech.rsi6:.1f}, RSI12={tech.rsi12:.1f}, RSI24={tech.rsi24:.1f})
- KDJ: K={tech.k_value:.1f}, D={tech.d_value:.1f}, J={tech.j_value:.1f}
- 布林带: 上轨={tech.boll_upper:.2f}, 中轨={tech.boll_middle:.2f}, 下轨={tech.boll_lower:.2f}, 位置={tech.boll_position:.1%}
- 成交量: {tech.volume_status.value} (量比={tech.volume_ratio:.2f})
- 乖离率: BIAS5={tech.bias5:.2f}%, BIAS10={tech.bias10:.2f}%, BIAS20={tech.bias20:.2f}%
- 综合评分: {tech.buy_score}/100
- 技术面操作建议: {tech.operation} ({tech.operation_reason})

## 支撑/压力位
- 支撑: {', '.join(f'{x:.2f}' for x in tech.support_levels)}
- 压力: {', '.join(f'{x:.2f}' for x in tech.resistance_levels)}

## 看多因素
{chr(10).join(f'- {r}' for r in tech.score_reasons) if tech.score_reasons else '- 无'}

## 风险因素
{chr(10).join(f'- {r}' for r in tech.risk_warnings) if tech.risk_warnings else '- 无'}

## 请按以下JSON格式回复:
{{
    "summary": "一句话核心结论",
    "operation": "买入/持有/卖出/观望",
    "entry_price": 建议买入价(数字),
    "stop_loss": 止损价(数字),
    "target_price": 目标价(数字),
    "risk_level": "低/中/高",
    "key_factors": ["看多因素1", "看多因素2"],
    "risk_warnings": ["风险1", "风险2"],
    "strategy": "建议的操作策略"
}}

注意：
1. 只输出JSON，不要多余文字
2. 价格要合理，基于当前价和技术位
3. 风险提示要具体
4. 不要建议追高（乖离率大时）
"""

    def analyze(self, tech: TechnicalResult) -> Optional[AIAdvice]:
        """使用 AI 进行分析"""
        if not self.is_available:
            console.print("[yellow]⚠ AI分析未配置，跳过 (请设置 LLM_PROVIDER 和 LLM_API_KEY)[/yellow]")
            return None

        try:
            from openai import OpenAI

            # 构建 client
            base_url = self.config.LLM_BASE_URL
            if not base_url:
                provider = self.config.LLM_PROVIDER.lower()
                if provider == "deepseek":
                    base_url = "https://api.deepseek.com/v1"
                elif provider == "openai":
                    base_url = "https://api.openai.com/v1"
                elif provider == "ollama":
                    base_url = "http://localhost:11434/v1"
                elif provider == "dmxapi":
                    base_url = "https://www.dmxapi.cn/v1"

            model = self.config.LLM_MODEL
            if not model:
                provider = self.config.LLM_PROVIDER.lower()
                if provider == "deepseek":
                    model = "deepseek-chat"
                elif provider == "openai":
                    model = "gpt-4o-mini"
                elif provider == "ollama":
                    model = "qwen2.5"
                elif provider == "dmxapi":
                    model = "qwen3.5-plus"

            client = OpenAI(
                api_key=self.config.LLM_API_KEY,
                base_url=base_url,
            )

            prompt = self._build_prompt(tech)
            console.print(f"[dim]正在请求 AI 分析 ({self.config.LLM_PROVIDER}/{model})...[/dim]")

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是专业的A股投资分析师，请基于技术指标给出客观、专业的投资建议。注意风险控制，不要建议追高。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1500,
            )

            content = response.choices[0].message.content.strip()

            # 提取 JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            data = json.loads(content)

            return AIAdvice(
                summary=data.get("summary", ""),
                operation=data.get("operation", "观望"),
                entry_price=float(data.get("entry_price", 0)),
                stop_loss=float(data.get("stop_loss", 0)),
                target_price=float(data.get("target_price", 0)),
                risk_level=data.get("risk_level", "中"),
                key_factors=data.get("key_factors", []),
                risk_warnings=data.get("risk_warnings", []),
                strategy=data.get("strategy", ""),
            )

        except json.JSONDecodeError as e:
            console.print(f"[red]✗ AI 返回 JSON 解析失败: {e}[/red]")
            return None
        except Exception as e:
            console.print(f"[red]✗ AI 分析失败: {e}[/red]")
            return None

    def analyze_by_code(self, code: str, strategy: str = "综合") -> Optional[AIAdvice]:
        """根据股票代码获取技术分析数据后进行AI分析"""
        from analyzer.technical import TechnicalAnalyzer
        from data_provider.base import DataFetcherManager
        from config import Config

        config = Config.get()
        manager = DataFetcherManager()
        manager.register_sources(config.DATA_SOURCES)

        # 获取行情和历史数据
        quote = manager.get_quote(code)
        hist = manager.get_history(code, config.HISTORY_DAYS)

        if hist is None or hist.empty:
            console.print(f"[red]无法获取 {code} 的历史数据[/red]")
            return None

        name = quote.name if quote else ""
        tech_analyzer = TechnicalAnalyzer()
        tech_result = tech_analyzer.analyze(hist, code=code, name=name)

        return self.analyze(tech_result)
