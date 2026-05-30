from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=50, description="密码")
    email: Optional[EmailStr] = Field(None, description="邮箱")

class UserLogin(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")
    captcha_key: str = Field(..., description="验证码KEY")
    captcha_value: str = Field(..., description="验证码值")

class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str]
    role: str
    status: str
    created_at: str
    last_login: Optional[str]

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6, max_length=50)

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse

class TokenData(BaseModel):
    user_id: Optional[int] = None
    username: Optional[str] = None
    role: Optional[str] = None

class CaptchaResponse(BaseModel):
    captcha_key: str
    captcha_image: str

class HistoryCreate(BaseModel):
    query_type: str = Field(..., description="查询类型：match/analyze")
    query_content: str = Field(..., description="查询内容")
    result_content: Optional[str] = Field(None, description="结果内容")

class HistoryResponse(BaseModel):
    id: int
    query_type: str
    query_content: str
    result_content: Optional[str]
    created_at: str

class FavoriteCreate(BaseModel):
    solution_name: str = Field(..., description="方案名称")
    solution_content: str = Field(..., description="方案内容")
    industry: Optional[str] = Field(None, description="行业")

class FavoriteResponse(BaseModel):
    id: int
    solution_name: str
    solution_content: str
    industry: Optional[str]
    created_at: str

class ProfileUpdate(BaseModel):
    email: Optional[EmailStr] = None

class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=50)
