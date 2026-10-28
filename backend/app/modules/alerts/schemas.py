from pydantic import BaseModel, Field


class ResolveIn(BaseModel):
    note: str = Field(default="", max_length=500)
