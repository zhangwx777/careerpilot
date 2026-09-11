from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models import APPLICATION_STATUS

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Industry = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
ApplicationStatus = Literal[*APPLICATION_STATUS]


class CompanyCreate(BaseModel):
    name: Name
    industry: Industry | None = None


class CompanyUpdate(BaseModel):
    name: Name | None = None
    industry: Industry | None = None

    @field_validator("name")
    @classmethod
    def name_cannot_be_null(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("公司名称不能为 null")
        return value


class CompanySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class CompanyRead(CompanySummary):
    industry: str | None
    created_at: datetime


class CompanyPage(BaseModel):
    items: list[CompanyRead]
    total: int
    page: int
    page_size: int


PositiveId = Annotated[int, Field(gt=0)]


class PositionCreate(BaseModel):
    company_id: PositiveId
    title: Name
    jd_text: str | None = None


class PositionUpdate(BaseModel):
    company_id: PositiveId | None = None
    title: Name | None = None
    jd_text: str | None = None

    @field_validator("company_id", "title")
    @classmethod
    def required_fields_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("必填字段不能为 null")
        return value


class PositionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    jd_text: str | None
    company: CompanySummary


class PositionRead(PositionSummary):
    company_id: int
    jd_text: str | None
    created_at: datetime


class PositionPage(BaseModel):
    items: list[PositionRead]
    total: int
    page: int
    page_size: int


class ApplicationCreate(BaseModel):
    company_name: Name
    position_title: Name
    jd_text: str | None = None
    status: ApplicationStatus = "已投递"
    applied_at: datetime | None = None
    note: str | None = None


class ApplicationUpdate(BaseModel):
    company_name: Name | None = None
    position_title: Name | None = None
    jd_text: str | None = None
    status: ApplicationStatus | None = None
    applied_at: datetime | None = None
    note: str | None = None

    @field_validator("company_name", "position_title")
    @classmethod
    def job_identity_cannot_be_null(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("公司和岗位不能为 null")
        return value

    @field_validator("status")
    @classmethod
    def status_cannot_be_null(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("阶段不能为 null")
        return value


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position_id: int
    status: ApplicationStatus
    applied_at: datetime | None
    note: str | None
    created_at: datetime
    position: PositionSummary


class ApplicationPage(BaseModel):
    items: list[ApplicationRead]
    total: int
    page: int
    page_size: int


class StatusTransition(BaseModel):
    status: ApplicationStatus


class ProviderRead(BaseModel):
    name: str
    model: str
