from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.llm.provider import chat
from app.models import NODE_TYPE

NodeType = Literal[*NODE_TYPE]
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class NoticeExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str | None = Field(default=None, max_length=200)
    position_title: str | None = Field(default=None, max_length=200)
    node_type: NodeType | None = None
    scheduled_at: datetime | None = None
    ends_at: datetime | None = None
    source: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_times(self):
        for field_name in ("scheduled_at", "ends_at"):
            value = getattr(self, field_name)
            if value is not None and value.utcoffset() is None:
                raise ValueError(f"{field_name} 必须包含时区")
        if (
            self.scheduled_at is not None
            and self.ends_at is not None
            and self.ends_at <= self.scheduled_at
        ):
            raise ValueError("ends_at 必须晚于 scheduled_at")
        return self


class NoticeParseError(Exception):
    pass


SYSTEM_PROMPT = """你是招聘通知信息抽取器。只输出一个 JSON 对象，不要输出 Markdown。
字段必须且只能是：company_name、position_title、node_type、scheduled_at、ends_at、source。
node_type 只能是：网申截止、笔试、一面、二面、三面、HR面、其他，无法确定时为 null。
scheduled_at 和 ends_at 使用带时区的 ISO 8601；无法确定完整日期或时刻时为 null。
company_name、position_title、source 无法确定时为 null。严禁猜测或补造信息。
相对日期以 Asia/Shanghai 的参考时间为准。"""


def extract_notice(
    raw_text: str, requested_at: datetime | None = None, provider: str = "qwen"
) -> NoticeExtraction:
    reference_time = requested_at or datetime.now(SHANGHAI_TZ)
    if reference_time.utcoffset() is None:
        reference_time = reference_time.replace(tzinfo=SHANGHAI_TZ)
    else:
        reference_time = reference_time.astimezone(SHANGHAI_TZ)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"参考时间：{reference_time.isoformat()}\n"
                f"待解析通知：\n{raw_text}"
            ),
        },
    ]
    try:
        content = chat(
            messages,
            provider=provider,
            response_format={"type": "json_object"},
        )
        if content is None:
            raise ValueError("模型未返回内容")
        return NoticeExtraction.model_validate_json(content)
    except (ValidationError, ValueError, TypeError) as exc:
        raise NoticeParseError(f"模型返回的抽取结果无效：{exc}") from exc
    except Exception as exc:
        raise NoticeParseError(f"模型调用失败：{exc}") from exc
