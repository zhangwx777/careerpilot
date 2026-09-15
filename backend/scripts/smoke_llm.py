"""逐个调通网页中已配置的厂商。

运行：`python -m scripts.smoke_llm`
"""

from app.db import SessionLocal
from app.llm.config_store import get_effective_config
from app.llm.provider import chat
from app.llm.registry import PROVIDER_NAMES


def main() -> None:
    msg = [{"role": "user", "content": "只回复两个字：你好"}]
    with SessionLocal() as db:
        for provider in PROVIDER_NAMES:
            try:
                cfg = get_effective_config(db, provider)
            except Exception:
                print(f"[跳过] {provider:10} 未配置")
                continue
            try:
                reply = chat(msg, provider=provider, config=cfg, generation="chat")
                print(f"[通过] {provider:10} {cfg['model']} -> {reply.strip()[:30]}")
            except Exception as e:
                print(f"[失败] {provider:10} {cfg['model']} -> {e}")


if __name__ == "__main__":
    main()
