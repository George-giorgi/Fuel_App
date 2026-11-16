from pydantic import BaseModel, Field


class InventoryStatus(BaseModel):
    available: bool
    items: list[dict[str, object]] = Field(default_factory=list)
    message: str
