from pydantic import BaseModel


class DashboardStatus(BaseModel):
    available: bool
    message: str
