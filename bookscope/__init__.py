"""BookScope — multi-dimensional book text analysis and visualization."""

__version__ = "1.7.0"

# 本地 .env 配置（BYOK key 等）——存在就把里面的变量灌进环境，不存在静默跳过。
# CLI 脚本（probe / eval_retrieval / run_batch）和 FastAPI app 都经由 import
# bookscope 走到这里，统一拿到 key，省得每个 session 手动重设环境变量。
# .env 只在本机、已进 .gitignore，绝不入库。Web 前端走浏览器 BYOK，不依赖此文件。
# python-dotenv 没装（纯生产环境只装 main 依赖）时不报错——那种场景走 BYOK 不读 .env。
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv()
except ModuleNotFoundError:
    pass
