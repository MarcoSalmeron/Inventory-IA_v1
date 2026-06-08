from fastapi import APIRouter,Request, HTTPException
from agent_services.app.models.schemas import  CredentialCreate
from agent_services.app.core.credentials_service import save_credential, get_credential
from agent_services.app.api.v1.business_units import get_business_units
from agent_services.app.api.v1.organizations import get_organizations
import pandas as pd


router = APIRouter(prefix="/agents", tags=["Agents"])

@router.get("/business-units")
def get_business_units():
    try:
        df = get_business_units()
        print(df)
        return df.to_json(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/organizations")
def get_organizations():
    df = get_organizations()
    return df.to_json(orient="records")

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
