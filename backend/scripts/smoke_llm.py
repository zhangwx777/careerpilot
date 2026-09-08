"""逐个调通四家模型。已配 key 的才测，没配的跳过。

运行：`python -m scripts.smoke_llm`
"""

from app.llm.provider import chat
from app.llm.registry import PROVIDERS, has_key

# 每家挑一个代表模型做连通性测试
TEST_MODELS = {
    "anthropic": "anthropic/claude-sonnet-4-20250514",
    "openai": "openai/gpt-4o-mini",
    "deepseek": "deepseek/deepseek-chat",
    "qwen": "qwen/qwen-plus",
}


def main() -> None:
    msg = [{"role": "user", "content": "只回复两个字：你好"}]
    for provider, model in TEST_MODELS.items():
        if not has_key(model):
            print(f"[跳过] {provider:10} 未配置 key")
            continue
        try:
            reply = chat(msg, model=model)
            print(f"[通过] {provider:10} {model} -> {reply.strip()[:30]}")
        except Exception as e:
            print(f"[失败] {provider:10} {model} -> {e}")


if __name__ == "__main__":
    main()
