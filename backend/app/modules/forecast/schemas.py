from pydantic import BaseModel, Field


class ForecastRequest(BaseModel):
    days: int = Field(7, ge=1, le=28)
    product_ids: list[int] | None = None
    warehouse_ids: list[str] | None = None
