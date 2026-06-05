from fastapi import APIRouter,Request
from agent_services.app.models.schemas import ChatRequest


router = APIRouter(prefix="/agents", tags=["Agents"])

@router.post("/chat")
def chat_analysis(request: ChatRequest,http_request: Request):
    return {"message": "OK"}
