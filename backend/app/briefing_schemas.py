from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class DailyBriefingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    briefing_date: date
    payload: dict
    created_at: datetime
    current_states: dict = Field(default_factory=lambda: {"timeline": {}, "preparation": {}})


class DailyBriefingPage(BaseModel):
    items: list[DailyBriefingRead]
    total: int
    page: int
    page_size: int
