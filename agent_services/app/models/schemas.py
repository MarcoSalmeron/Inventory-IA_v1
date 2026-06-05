from pydantic import BaseModel
from typing import Optional

class ChatRequest(BaseModel):
    question: Optional[str]