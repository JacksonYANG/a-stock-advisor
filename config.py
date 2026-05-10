"""
配置管理模块 - 单例模式
从环境变量和 .env 文件加载配置
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv(Path(__file__).parent / ".env")


@dataclass
class Config:
    """全局配置"""
    # 项目路径
    BASE_DIR: Path = field(default_factory=lambda: Path(__file__).parent)

    # 数据源
    DATA_SOURCES: List[str] = field(default_factory=lambda: [
        s.strip() for s in os.getenv("DATA_SOURCES", "efinance,akshare").split(",") if s.strip()
    ])
    TUSHARE_TOKEN: Optional[str] = field(default_factory=lambda: os.getenv("TUSHARE_TOKEN", ""))

    # 自选股
    WATCH_LIST: List[str] = field(default_factory=lambda: [
        s.strip() for s in os.getenv("WATCH_LIST", "").split(",") if s.strip()
    ])

    # LLM 配置
    LLM_PROVIDER: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", ""))
    LLM_API_KEY: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    LLM_MODEL: str = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
    LLM_BASE_URL: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", ""))

    # 通知渠道
    TELEGRAM_BOT_TOKEN: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    TELEGRAM_CHAT_ID: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    WECHAT_WEBHOOK_URL: str = field(default_factory=lambda: os.getenv("WECHAT_WEBHOOK_URL", ""))

    # 邮件
    SMTP_HOST: str = field(default_factory=lambda: os.getenv("SMTP_HOST", ""))
    SMTP_PORT: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "465")))
    SMTP_USER: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    SMTP_PASSWORD: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    EMAIL_TO: str = field(default_factory=lambda: os.getenv("EMAIL_TO", ""))

    # 分析参数
    HISTORY_DAYS: int = field(default_factory=lambda: int(os.getenv("HISTORY_DAYS", "120")))
    REPORT_FORMAT: str = field(default_factory=lambda: os.getenv("REPORT_FORMAT", "markdown"))
    REPORT_DIR: Path = field(default_factory=lambda: Path(os.getenv("REPORT_DIR", "reports")))
    DATA_DIR: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "data")))

    # 日志
    LOG_LEVEL: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    LOG_FILE: str = field(default_factory=lambda: os.getenv("LOG_FILE", "logs/a-stock-advisor.log"))

    _instance: Optional["Config"] = field(default=None, init=False, repr=False)

    @classmethod
    def get(cls) -> "Config":
        if cls._instance is None:
            cls._instance = cls()
            # 确保目录存在
            cls._instance.REPORT_DIR.mkdir(parents=True, exist_ok=True)
            cls._instance.DATA_DIR.mkdir(parents=True, exist_ok=True)
            Path(cls._instance.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        return cls._instance

    @property
    def has_llm(self) -> bool:
        return bool(self.LLM_PROVIDER and self.LLM_API_KEY)

    @property
    def has_telegram(self) -> bool:
        return bool(self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHAT_ID)

    @property
    def has_wechat(self) -> bool:
        return bool(self.WECHAT_WEBHOOK_URL)

    @property
    def has_email(self) -> bool:
        return bool(self.SMTP_HOST and self.SMTP_USER and self.EMAIL_TO)

    def __repr__(self) -> str:
        return (
            f"Config(data_sources={self.DATA_SOURCES}, "
            f"watch_list={self.WATCH_LIST}, "
            f"llm={self.has_llm}, "
            f"telegram={self.has_telegram})"
        )
