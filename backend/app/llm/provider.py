"""统一的多模型调用入口。

用 LiteLLM 把 claude/openai/deepseek/qwen 收敛到一个 chat() 函数。
业务代码按任务类型（parse / reason）选模型，不关心底层是哪家。
"""

import litellm

from app.config import settings
from app.llm.registry import PROVIDERS, has_key, provider_of

# 任务类型 -> 默认模型（来自 .env，可改）
TASK_MODELS = {
    "parse": settings.model_parse,
    "reason": settings.model_reason,
}


def chat(messages: list[dict], task: str = "reason", model: str | None = None) -> str:
    """调用大模型，返回文本内容。

    messages: [{"role": "user"/"system"/"assistant", "content": "..."}]
    task: "parse"（便宜快）或 "reason"（能力强），决定默认模型
    model: 显式指定 LiteLLM 模型名则覆盖 task 默认
    """
    chosen = model or TASK_MODELS.get(task, settings.model_reason)
    if not has_key(chosen):
        raise RuntimeError(f"模型 {chosen} 对应的厂商未配置 API key")

    cfg = PROVIDERS[provider_of(chosen)]
    kwargs: dict = {"model": chosen, "messages": messages, "api_key": cfg["api_key"]}
    if cfg["api_base"]:
        kwargs["api_base"] = cfg["api_base"]

    resp = litellm.completion(**kwargs)
    return resp.choices[0].message.content
