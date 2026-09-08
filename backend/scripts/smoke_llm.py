"""逐个调通已配置的厂商。配了 key 的才测，用各自 .env 里的 model。

运行：`python -m scripts.smoke_llm`
"""

from app.llm.provider import chat
from app.llm.registry import PROVIDERS, has_key


def main() -> None:
    msg = [{"role": "user", "content": "只回复两个字：你好"}]
    for provider, cfg in PROVIDERS.items():
        if not has_key(provider):
            print(f"[跳过] {provider:10} 未配置 key")
            continue
        if not cfg["model"]:
            print(f"[跳过] {provider:10} 已配 key 但未配 model")
            continue
        try:
            reply = chat(msg, provider=provider)
            print(f"[通过] {provider:10} {cfg['model']} -> {reply.strip()[:30]}")
        except Exception as e:
            print(f"[失败] {provider:10} {cfg['model']} -> {e}")


if __name__ == "__main__":
    main()
