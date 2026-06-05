from fastapi import APIRouter,Request, HTTPException
from agent_services.app.models.schemas import ChatRequest, CredentialCreate
from agent_services.app.core.credentials_service import save_credential, get_credential


router = APIRouter(prefix="/agents", tags=["Agents"])

@router.post("/chat")
def chat_analysis(request: ChatRequest,http_request: Request):
    return {"message": "OK"}

# --- Credentials endpoints ---  
  
@router.post("/credentials")  
def create_credential(body: CredentialCreate):  
    return save_credential(**body.model_dump())  
  
  
@router.get("/credentials/{credential_name}")  
def fetch_credential(credential_name: str):  
    creds = get_credential(credential_name)  
    if not creds:  
        raise HTTPException(status_code=404, detail="Credencial no encontrada")  
    return creds  
