# A股交易决策辅助系统

一套面向中国A股市场的交易信息获取、技术分析、智能决策辅助系统。

参考项目: [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis)

## 功能特性

- 🏦 **多数据源支持**: efinance(东方财富) + akshare，自动故障切换
- 📊 **技术分析引擎**: MA/MACD/RSI/KDJ/布林带/成交量/筹码分布
- 🤖 **AI决策辅助**: 支持接入 DeepSeek/OpenAI/Ollama 进行智能分析
- 📰 **新闻资讯**: 个股相关新闻聚合与情感分析
- 📈 **市场总览**: 大盘指数、板块涨跌、涨跌统计
- 📋 **策略系统**: 内置多种交易策略(YAML配置)
- 📱 **多渠道推送**: Telegram/微信/邮件通知
- 💾 **数据持久化**: SQLite本地存储历史数据与分析结果

## 快速开始

```bash
# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 复制配置文件
cp .env.example .env
# 编辑 .env 填入你的配置

# 运行分析（单只股票）
python main.py analyze --stock 000001

# 运行分析（自选股列表）
python main.py analyze --stocks 000001,600519,300750

# 市场总览
python main.py market

# 每日定时分析
python main.py schedule --time 15:30

# 启动 Web 服务
python main.py serve --port 8080
```

## 项目结构

```
a-stock-advisor/
├── main.py                  # CLI入口
├── config.py                # 配置管理
├── requirements.txt         # 依赖清单
├── .env.example             # 环境变量模板
├── data_provider/           # 数据获取层
│   ├── base.py              # 数据源基类与管理器
│   ├── efinance_fetcher.py  # 东方财富数据源
│   └── akshare_fetcher.py   # AkShare数据源
├── analyzer/                # 分析引擎
│   ├── technical.py         # 技术指标分析
│   ├── market.py            # 市场总览分析
│   └── ai_advisor.py        # AI决策辅助
├── strategies/              # 交易策略(YAML)
│   ├── bull_trend.yaml      # 牛市趋势策略
│   ├── ma_cross.yaml        # 均线交叉策略
│   └── volume_breakout.yaml # 放量突破策略
├── templates/               # 报告模板
├── reports/                 # 输出报告
├── data/                    # 本地数据缓存
├── utils/                   # 工具函数
│   ├── formatting.py        # 格式化工具
│   └── trading_calendar.py  # 交易日历
└── tests/                   # 测试用例
```

## 配置说明

编辑 `.env` 文件进行配置：

```env
# 数据源配置
DATA_SOURCES=efinance,akshare

# 自选股列表
WATCH_LIST=000001,600519,300750,002594

# AI分析 (可选)
LLM_PROVIDER=deepseek
LLM_API_KEY=your-api-key
LLM_MODEL=deepseek-chat

# 通知渠道 (可选)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```
