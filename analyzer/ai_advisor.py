"""
AI 决策辅助模块
支持 DeepSeek / OpenAI / Ollama 等多种 LLM
基于技术分析结果 + 新闻资讯，生成智能投资建议
"""

import json
import re
from typing import Optional
from dataclasses import dataclass, field
from rich.console import Console

from config import Config
from analyzer.technical import TechnicalResult
from data_provider.stock_names import resolve_stock_name

console = Console()


@dataclass
class AIAdvice:
    """AI 分析建议"""
    # New enriched fields (first)
    one_sentence: str = ""               # 一句话核心结论
    time_sensitivity: str = ""           # 时间敏感度 (短线/中线/中线偏长)
    decision_type: str = "hold"          # 决策类型 (buy/hold/sell)
    confidence: int = 0                  # 信心指数 0-100
    position_advice: dict = field(default_factory=dict)   # 持仓建议
    battle_plan: dict = field(default_factory=dict)       # 作战计划
    data_perspective: dict = field(default_factory=dict)  # 数据透视
    analysis_detail: str = ""            # 详细分析文本 (200-300 chars)

    # Original fields (kept for backward compatibility)
    summary: str = ""                    # 核心结论
    operation: str = "观望"              # 操作建议
    entry_price: float = 0.0             # 建议买入价
    stop_loss: float = 0.0               # 止损价
    target_price: float = 0.0            # 目标价
    risk_level: str = "中"               # 风险等级: 低/中/高
    key_factors: list = field(default_factory=list)       # 关键因素
    risk_warnings: list = field(default_factory=list)     # 风险提示
    strategy: str = ""                   # 建议策略

    def to_markdown(self) -> str:
        lines = [
            "🤖 AI 智能分析",
            "=" * 50,
        ]
        if self.one_sentence:
            lines.append(f"💡 一句话结论: {self.one_sentence}")
        lines.append(f"📌 核心结论: {self.summary}")
        if self.decision_type:
            lines.append(f"🎯 决策类型: {self.decision_type.upper()}")
        lines.append(f"📋 操作建议: {self.operation}")
        lines.append(f"⚠️ 风险等级: {self.risk_level}")
        if self.confidence:
            lines.append(f"🔢 信心指数: {self.confidence}/100")
        if self.time_sensitivity:
            lines.append(f"⏰ 时间敏感度: {self.time_sensitivity}")
        if self.entry_price:
            lines.append(f"💰 建议买入价: {self.entry_price:.2f}")
        if self.stop_loss:
            lines.append(f"🛑 止损价: {self.stop_loss:.2f}")
        if self.target_price:
            lines.append(f"🎯 目标价: {self.target_price:.2f}")
        if self.strategy:
            lines.append(f"📊 策略: {self.strategy}")

        if self.position_advice:
            lines.append("\n📦 持仓建议:")
            if self.position_advice.get("no_position"):
                lines.append(f"  🫙 空仓: {self.position_advice['no_position']}")
            if self.position_advice.get("has_position"):
                lines.append(f"  📈 持仓: {self.position_advice['has_position']}")

        if self.battle_plan:
            lines.append("\n⚔️ 作战计划:")
            bp = self.battle_plan
            if bp.get("ideal_buy"):
                lines.append(f"  ✅ 理想买入: {bp['ideal_buy']}")
            if bp.get("secondary_buy"):
                lines.append(f"  🔄 次选买入: {bp['secondary_buy']}")
            if bp.get("stop_loss"):
                lines.append(f"  🛑 止损: {bp['stop_loss']}")
            if bp.get("take_profit"):
                lines.append(f"  🎯 止盈: {bp['take_profit']}")
            if bp.get("suggested_position"):
                lines.append(f"  📐 建议仓位: {bp['suggested_position']}")
            if bp.get("risk_control"):
                lines.append(f"  🛡️ 风控: {bp['risk_control']}")

        if self.data_perspective:
            lines.append("\n📊 数据透视:")
            dp = self.data_perspective
            if dp.get("trend_status"):
                lines.append(f"  趋势: {dp['trend_status']}")
            if dp.get("price_position"):
                lines.append(f"  价格位置: {dp['price_position']}")
            if dp.get("volume_analysis"):
                lines.append(f"  量能: {dp['volume_analysis']}")

        if self.analysis_detail:
            lines.append(f"\n📝 详细分析:\n{self.analysis_detail}")

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

    SYSTEM_PROMPT = (
        "你是拥有15年A股实战经验的专业投资分析师。"
        "你精通技术分析（均线、MACD、KDJ、RSI、布林带、筹码分布），"
        "擅长捕捉趋势拐点和买卖时机。"
        "你的分析风格：简洁有力、数据说话、风险第一。"
    )

    def __init__(self):
        self.config = Config.get()
        self._client = None
        self._resolved_model = None

    def _get_client(self):
        """Lazy-create and cache the OpenAI client."""
        if self._client is not None:
            return self._client, self._resolved_model

        from openai import OpenAI

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

        self._client = OpenAI(
            api_key=self.config.LLM_API_KEY,
            base_url=base_url,
        )
        self._resolved_model = model
        return self._client, self._resolved_model

    @property
    def is_available(self) -> bool:
        return self.config.has_llm

    def _build_prompt(self, tech: TechnicalResult) -> str:
        """构建分析提示词"""
        stock_name = tech.name or resolve_stock_name(tech.code) or tech.code

        return f"""请对以下A股进行全方位技术分析，像一位拥有15年实战经验的专业投资分析师一样思考。

## 股票信息
- 代码: {tech.code}
- 名称: {stock_name}
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

## 请综合分析以下维度:
1. 均线排列：是否多头/空头排列，短期均线与长期均线的位置关系
2. MACD动量：DIF/DEA金叉/死叉状态，红绿柱变化趋势
3. RSI超买超卖：RSI指标所处区间，是否存在背离信号
4. 量价配合：成交量与价格的配合关系，是否有放量突破或缩量回调
5. 布林带位置：价格在布林带中的位置，是否接近压力或支撑
6. 关键支撑/压力位：重要的技术价位
7. 风险收益比：买入的潜在收益与风险的比较
8. 仓位建议：根据信号强度建议的仓位比例

## 请严格按以下JSON格式回复:
{{
    "one_sentence": "一句话核心结论（最重要的判断，要精准有力）",
    "summary": "50字以内的分析摘要",
    "analysis_detail": "200-300字的详细技术分析解读，包括均线、MACD、量价、布林带等维度的综合分析",
    "decision_type": "buy/hold/sell（三选一）",
    "operation": "逢低买入/持有观望/减仓/观望等",
    "confidence": 75,
    "risk_level": "低/中/高",
    "time_sensitivity": "短线/中线/中线偏长",
    "entry_price": 20.15,
    "stop_loss": 19.50,
    "target_price": 22.80,
    "key_factors": ["看多因素1", "看多因素2"],
    "risk_warnings": ["风险1", "风险2"],
    "strategy": "建议的操作策略描述",
    "position_advice": {{
        "no_position": "空仓者的操作建议",
        "has_position": "持仓者的操作建议"
    }},
    "battle_plan": {{
        "ideal_buy": 20.10,
        "secondary_buy": 20.50,
        "stop_loss": 19.50,
        "take_profit": 22.80,
        "suggested_position": "3成仓位",
        "risk_control": "跌破XX元减仓"
    }},
    "data_perspective": {{
        "trend_status": "多头排列/空头排列/震荡",
        "price_position": "均线之上/均线之下/均线附近",
        "volume_analysis": "放量/缩量/平量"
    }}
}}

注意：
1. 只输出JSON，不要多余文字
2. 价格要合理，基于当前价和技术位
3. 风险提示要具体
4. 不要建议追高（乖离率大时）
5. one_sentence要精准有力，直击要害
6. confidence范围0-100，代表分析信心
7. battle_plan中的价格必须是数字
"""

    @staticmethod
    def _extract_json(content: str) -> Optional[dict]:
        """Robust JSON extraction from LLM response."""
        # 1) Try direct parse
        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            pass

        # 2) Try extracting from ```json ... ``` code block
        m = re.search(r"```json\s*\n?(.*?)```", content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except (json.JSONDecodeError, ValueError):
                pass

        # 3) Try extracting from ``` ... ``` code block (without json tag)
        m = re.search(r"```\s*\n?(.*?)```", content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except (json.JSONDecodeError, ValueError):
                pass

        # 4) Try finding the first { ... } with balanced braces
        start = content.find("{")
        if start != -1:
            depth = 0
            for i in range(start, len(content)):
                if content[i] == "{":
                    depth += 1
                elif content[i] == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = content[start:i + 1]
                        try:
                            return json.loads(candidate)
                        except (json.JSONDecodeError, ValueError):
                            break
        return None

    def analyze(self, tech: TechnicalResult) -> Optional[AIAdvice]:
        """使用 AI 进行分析"""
        if not self.is_available:
            console.print("[yellow]⚠ AI分析未配置，跳过 (请设置 LLM_PROVIDER 和 LLM_API_KEY)[/yellow]")
            return None

        try:
            client, model = self._get_client()

            prompt = self._build_prompt(tech)
            console.print(f"[dim]正在请求 AI 分析 ({self.config.LLM_PROVIDER}/{model})...[/dim]")

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=3000,
            )

            content = response.choices[0].message.content.strip()
            data = self._extract_json(content)

            if data is None:
                console.print("[red]✗ AI 返回内容无法解析为 JSON[/red]")
                return None

            return AIAdvice(
                one_sentence=data.get("one_sentence", ""),
                time_sensitivity=data.get("time_sensitivity", ""),
                decision_type=data.get("decision_type", "hold"),
                confidence=int(data.get("confidence", 0)),
                position_advice=data.get("position_advice", {}),
                battle_plan=data.get("battle_plan", {}),
                data_perspective=data.get("data_perspective", {}),
                analysis_detail=data.get("analysis_detail", ""),
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
