from fastapi import APIRouter, HTTPException
from agent_services.app.models.schemas import  CredentialCreate, CredentialUpdate, ProcessConfig
from agent_services.app.core.credentials_service import save_credential, get_credential, update_credential, delete_credential, activate_credential, save_process_config, get_process_config
from agent_services.app.core.soap_service import run_bulk_export
from agent_services.app.core.rag import InventoryEmbeddingsRAG
from agent_services.app.core.db_conn import create_analysis_run
from agent_services.app.api.v1.business_units import get_business_units
from agent_services.app.api.v1.organizations import get_organizations
from agent_services.app.services.inventory_service import process_inventory_zip

router = APIRouter(prefix="/agents", tags=["Agents"])

rag = InventoryEmbeddingsRAG()

# ################################# #
# --- Oracle API REST Endpoints --- # 
# ################################# #

@router.get("/business-units/{credential_name}")
def fetch_business_units(credential_name: str):
    try:
        df = get_business_units(credential_name)
        return df.to_json(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/organizations/{credential_name}/{management_business_unit_id}")
def fetch_organizations(credential_name: str, management_business_unit_id: str = None):
    try:
        df = get_organizations(credential_name, management_business_unit_id)
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

@router.post("/process-config")
def create_process_config(body: ProcessConfig):
    return save_process_config(
        process_code=body.processCode,
        inv_organization_id=body.parameters.invOrganizationId,
    )

# ##################### #
# --- SOAP Services (Solo extraccion y persistencia)--- #
# ##################### #

@router.post("/{enterprise_id}/bulk-export")  
async def trigger_bulk_export(enterprise_id: int):  
    try:  
        soap_result = run_bulk_export(enterprise_id)  
  
        # registrar primer paso del pipeline (extraccion de inventario) ──  
        create_analysis_run(  
            request_id=soap_result["request_id"],  
            status="EXTRACTING",  
        )  
  
        job_id = get_process_config(enterprise_id)["enterprise_code"]  
        chunks = process_inventory_zip(soap_result["zip_path"], soap_result["request_id"], job_id)  
        return {"message": "Extraccion completada", "chunks": chunks}  
    except Exception as e:  
        raise HTTPException(status_code=500, detail=str(e))
    
# #################### #
# --- RAG Services (Pipeline COMPLETO)--- #
# #################### #
@router.post('/{enterprise_id}/{producto}/analysis}')
async def start_analysis(enterprise_id: int, producto: str):
    try:
        print(f'\n{"#"*30}\nAnalisis Orquestador\n{"#"*30}\n')
        print(f'\n{"#"*30}\n1.- Extraccion de Inventario\n{"#"*30}\n')

        soap_result = run_bulk_export(enterprise_id)

        create_analysis_run(
            request_id=soap_result["request_id"],
            status="EXTRACTING",
        )

        job_id = get_process_config(enterprise_id)["enterprise_code"]
        chunks = process_inventory_zip(soap_result["zip_path"], soap_result["request_id"], job_id)

        print(f'\n{"#" * 30}\n2.- Embeddings\n{"#" * 30}\n')
        rag.cargar_inv_embeddings(chunks, soap_result["request_id"], job_id)

        print(f'\n{"#" * 30}\n3.- Similitud (score ≥ 0.85)\n{"#" * 30}\n')
        productos_similares = rag.buscar(producto, soap_result["request_id"])

        rag.cerrar()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))