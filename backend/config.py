from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ------- 数据库 -------
    database_url: str = (
        "postgresql+asyncpg://knowledge:knowledge123@localhost:5432/knowledge_agent"
    )

    # ------- LLM API keys -------
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    # ------- 模型路由：Agent -> (provider, model) -------
    model_routing: dict = {
        "collector": {"provider": "deepseek", "model": "deepseek-chat"},
        "curator": {"provider": "deepseek", "model": "deepseek-chat"},
        "librarian": {"provider": "deepseek", "model": "deepseek-chat"},
        "editor": {"provider": "deepseek", "model": "deepseek-chat"},
    }

    # ------- Embedding -------
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cpu"
    embedding_dimension: int = 1024

    # ------- 检索参数 -------
    dense_top_k: int = 20
    sparse_top_k: int = 20
    rrf_k: int = 60
    final_top_k: int = 5

    # ------- 分块参数 -------
    chunk_min_tokens: int = 200
    chunk_max_tokens: int = 1500
    chunk_overlap_ratio: float = 0.1

    # ------- 记忆参数 -------
    short_term_max_rounds: int = 20
    interest_decay_days: int = 30
    interest_dormant_days: int = 90
    interest_auto_capture_threshold: int = 5
    session_summary_trigger_rounds: int = 10

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
