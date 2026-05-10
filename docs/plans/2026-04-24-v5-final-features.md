# A股项目增强V5：游资追踪器 + 测试 + PDF报告 + 组合分析 + 参数优化 + 交易日志 + Docker

> **For subagents:** Implement all features in parallel.

---

## 模块一：游资席位映射追踪器（按 a-stock-hot-money-tracker 技能规划）

### Files:
- Create: `data_provider/hot_money_tracker.py` — 核心数据引擎
- Create: `data/seat_registry.yaml` — 游资→席位映射注册表
- Modify: `main.py` — 添加 hot_money CLI 命令

### Data Source: AKShare 东方财富接口
- `stock_lhb_hyyyb_em(date)` — 每日活跃营业部
- `stock_lhb_detail_em(date)` — 龙虎榜每日明细
- `stock_lhb_jgmmtj_em(date)` — 机构买卖统计
- `stock_lhb_yybph_em(date)` — 营业部排行 (含胜率)

### Known Seat → 游资 Mappings:
- 佛山系: 国盛证券佛山分公司, 光大证券佛山绿景路, 光大证券佛山季华六路
- 湖里大道: 兴业证券厦门湖里大道证券营业部
- 成都系: 国泰君安成都北一环路, 华泰成都蜀金路
- 拉萨帮(散户): 东方财富拉萨团结路第一/第二, 拉萨金融城南环路
- 炒股养家: 华鑫证券相关席位

---

## 模块二：单元测试

### Files:
- Create: `tests/test_technical.py`
- Create: `tests/test_storage.py`
- Create: `tests/test_strategy_engine.py`
- Create: `tests/test_config.py`
- Create: `tests/conftest.py`

---

## 模块三：PDF分析报告

### Files:
- Create: `analyzer/report_generator.py`
- Modify: `main.py` — 添加 report CLI 命令
- Add dependency: `reportlab` or `fpdf2`

---

## 模块四：组合持仓分析

### Files:
- Create: `analyzer/portfolio_analyzer.py`
- Modify: `main.py` — 添加 portfolio-analysis CLI 命令

---

## 模块五：策略参数优化

### Files:
- Create: `analyzer/strategy_optimizer.py`
- Modify: `main.py` — 添加 optimize CLI 命令

---

## 模块六：交易日志

### Files:
- Create: `analyzer/trade_journal.py`
- Modify: `data_provider/storage.py` — 添加 TradeJournal 模型
- Modify: `main.py` — 添加 journal CLI 命令

---

## 模块七：市场宽度指标

### Files:
- Create: `analyzer/market_breadth.py`
- Modify: `main.py` — 添加 breadth CLI 命令

---

## 模块八：Docker部署

### Files:
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`

---

## 模块九：增强Web仪表盘

### Files:
- Modify: `web_dashboard.py` — 添加更多API
- Modify: `templates/dashboard.html` — 添加更多面板

---

## 模块十：增强回测（模拟交易）

### Files:
- Create: `analyzer/paper_trading.py`
- Modify: `main.py` — 添加 paper-trade CLI 命令
