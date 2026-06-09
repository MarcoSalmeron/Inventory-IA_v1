from pydantic import BaseModel
from typing import Optional

class ChatRequest(BaseModel):
    question: Optional[str]

class CredentialCreate(BaseModel):  
    credential_name: str  
    host: str  
    username: str  
    user_password: str  
    estatus: Optional[str] = "ACTIVE"  
    created_by: Optional[str] = None  
    attribute1: Optional[str] = None  
    attribute2: Optional[str] = None  
    attribute3: Optional[str] = None  
    attribute4: Optional[str] = None  
    attribute5: Optional[str] = None

class CredentialUpdate(BaseModel):  
    host: Optional[str] = None  
    username: Optional[str] = None  
    user_password: Optional[str] = None  
    estatus: Optional[str] = None  
    updated_by: Optional[str] = None  
    attribute1: Optional[str] = None  
    attribute2: Optional[str] = None  
    attribute3: Optional[str] = None  
    attribute4: Optional[str] = None  
    attribute5: Optional[str] = None