from fastapi import APIRouter,Request, HTTPException
from agent_services.app.models.schemas import  CredentialCreate, CredentialUpdate
from agent_services.app.core.credentials_service import save_credential, get_credential, update_credential, delete_credential, activate_credential
from agent_services.app.api.v1.business_units import get_business_units
from agent_services.app.api.v1.organizations import get_organizations

router = APIRouter(prefix="/agents", tags=["Agents"])

# ############################# #
# --- Services Endpoints --- # 
# ############################# #

@router.get("/business-units/{credential_name}")
def fetch_business_units(credential_name: str):
    try:
        df = get_business_units(credential_name)
        return df.to_json(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/organizations/{credential_name}")
def fetch_organizations(credential_name: str):
    try:
        df = get_organizations(credential_name)
        return df.to_json(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ############################# #
# --- Credentials Endpoints --- # 
# ############################# #

@router.post("/credentials")  
def create_credential(body: CredentialCreate):  
    return save_credential(**body.model_dump())  

@router.put("/credentials/{credential_name}")  
def edit_credential(credential_name: str, body: CredentialUpdate):  
    result = update_credential(credential_name, **body.model_dump())  
    if result is None:  
        raise HTTPException(status_code=404, detail="Credencial no encontrada")  
    return result  
  
@router.get("/credentials/{credential_name}")  
def fetch_credential(credential_name: str):  
    creds = get_credential(credential_name)  
    if not creds:  
        raise HTTPException(status_code=404, detail="Credencial no encontrada")  
    return creds  

@router.delete("/credentials/{credential_name}")  
def remove_credential(credential_name: str):  
    result = delete_credential(credential_name)  
    if result is None:  
        raise HTTPException(status_code=404, detail="Credencial no encontrada")  
    return result

@router.put("/credentials/activate/{credential_name}")  
def add_credential(credential_name: str):
    result = activate_credential(credential_name)
    if result is None:  
        raise HTTPException(status_code=404, detail="Credencial no encontrada")  
    return result  