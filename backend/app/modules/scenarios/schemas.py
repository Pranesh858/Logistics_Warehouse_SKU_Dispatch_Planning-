from pydantic import BaseModel, Field, model_validator


class DemandChange(BaseModel):
    """More or less demand for one SKU or one category. 1.2 = 20% more."""
    product_id: int | None = None
    category: str | None = None
    multiplier: float = Field(gt=0, le=10)

    @model_validator(mode="after")
    def one_target(self):
        if (self.product_id is None) == (self.category is None):
            raise ValueError("Give either product_id or category")
        return self


class StockChange(BaseModel):
    """Stock at one warehouse up or down. -10 = 10% less."""
    warehouse_id: str
    change_pct: float = Field(ge=-100, le=500)


class BlockSku(BaseModel):
    """Treat a SKU as blocked, at one warehouse or (without warehouse_id) at all of them."""
    product_id: int
    warehouse_id: str | None = None


class ScenarioIn(BaseModel):
    demand: list[DemandChange] = []
    stock: list[StockChange] = []
    block: list[BlockSku] = []
    warehouse_id: str | None = None          # an admin can narrow the comparison to one warehouse
