from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class SignupRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("display_name cannot be blank")
        if any(ord(character) < 32 for character in value):
            raise ValueError("display_name cannot contain control characters")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)
    device_name: str = Field(default="웹 브라우저", min_length=1, max_length=80)

    @field_validator("device_name")
    @classmethod
    def strip_device_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("device_name is invalid")
        return value


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    status: str
    email_verified: bool
    created_at: datetime


class SignupResponse(BaseModel):
    user: UserPublic


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class ActionTokenRequest(BaseModel):
    token: SecretStr = Field(min_length=32, max_length=256)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(ActionTokenRequest):
    new_password: SecretStr = Field(min_length=12, max_length=128)


class PasswordChangeRequest(BaseModel):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=12, max_length=128)


class AcceptedResponse(BaseModel):
    message: str


class SessionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_name: str
    created_at: datetime
    last_seen_at: datetime
    current: bool = False


class SessionListResponse(BaseModel):
    sessions: list[SessionPublic]
