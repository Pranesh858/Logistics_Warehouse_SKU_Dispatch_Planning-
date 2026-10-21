from datetime import datetime

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern="^(admin|planner|viewer)$")
    warehouse_id: str | None = None


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: str | None = Field(default=None, pattern="^(admin|planner|viewer)$")
    warehouse_id: str | None = None
    active: bool | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    name: str
    role: str
    warehouse_id: str | None
    active: bool
    created_at: datetime
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}
