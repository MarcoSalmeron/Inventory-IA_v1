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

class ParameterConfig(BaseModel):
    invOrganizationId: int

class ProcessConfig(BaseModel):
  processCode: str
  parameters: ParameterConfig

class AnalysisRequest(BaseModel):  
    categoria: Optional[str] = "ALL"   # "ALL" o nombre de categoría  
    umbral: Optional[float] = 0.85     # mínimo final_score para entrar al grupo  
    top_k: Optional[int] = 10          # candidatos a recuperar por HNSW antes del umbral  
    group_risk: Optional[str] = "medium"