from __future__ import annotations

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    model_validator,
)


class LoginRequest(BaseModel):
    email: EmailStr | None = None
    username: str | None = Field(default=None, min_length=1, max_length=100)
    password: SecretStr

    @model_validator(mode="after")
    def require_one_login_identifier(self) -> LoginRequest:
        if self.email is None and (self.username is None or not self.username.strip()):
            raise ValueError("Provide a username or email address.")
        if self.username is not None and not self.username.strip():
            raise ValueError("The username must not be empty.")
        if self.email is not None and self.username is not None:
            raise ValueError("Provide either a username or an email address.")
        return self

    @property
    def identifier(self) -> str:
        return self.username if self.username is not None else str(self.email)


class EmployeeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    username: str | None
    name: str
    role: str
