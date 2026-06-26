from fastapi import APIRouter, HTTPException
from agent_services.app.models.schemas import  CredentialCreate, CredentialUpdate, ProcessConfig
from agent_services.app.core.credentials_service import save_credential, get_credential, update_credential, delete_credential, activate_credential, save_process_config, get_process_config
from agent_services.app.core.soap_service import run_bulk_export
from agent_services.app.core.rag import InventoryEmbeddingsRAG
from agent_services.app.core.db_conn import create_analysis_run, update_analysis_run_status, update_analysis_run_kpis
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

# ###################################################### #
# --- SOAP Services (Solo extraccion y persistencia) --- #
# ###################################################### #

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
    
# ######################################## #
# --- RAG Services (Pipeline COMPLETO) --- #
# ######################################## #
@router.post('/{enterprise_id}/{producto}/analysis')  
async def start_analysis(enterprise_id: int, producto: str):  
    request_id = None  
    try:  
        # ── FASE 1: EXTRACCIÓN ──────────────────────────────────────────────  
        print(f'\n{"#"*30}\n1.- Extraccion de Inventario\n{"#"*30}\n')  
  
        soap_result = run_bulk_export(enterprise_id)  
        request_id  = soap_result["request_id"]  
  
        create_analysis_run(request_id=request_id, status="EXTRACTING")  
  
        job_id = get_process_config(enterprise_id)["enterprise_code"]  
        chunks = process_inventory_zip(soap_result["zip_path"], request_id, job_id)  
        # ↑ internamente llama update_analysis_run_org(status="EXTRACTED")  
        # ↑ ya guarda organization_id, organization_code, business_unit_id, business_unit_name  
  
        # Actualizar KPI: total de ítems extraídos  
        update_analysis_run_kpis(request_id, items_total=len(chunks))  
  
        # ── FASE 2: EMBEDDINGS ──────────────────────────────────────────────  
        print(f'\n{"#"*30}\n2.- Embeddings\n{"#"*30}\n')  
  
        update_analysis_run_status(request_id, "EMBEDDING")  
        insertados = rag.cargar_inv_embeddings(chunks, request_id, job_id)  
        update_analysis_run_kpis(request_id, items_embedded=insertados)  
        update_analysis_run_status(request_id, "EMBEDDED")  
  
        # ── FASE 3: ANÁLISIS SEMÁNTICO ──────────────────────────────────────  
        # Iterar sobre los chunks filtrando por la categoría del parámetro `producto`.  
        # Cada ítem actúa como anchor → buscar_y_persistir() encuentra su grupo  
        # y lo persiste en inv_similarity_results con is_anchor + candidatos.  
        print(f'\n{"#"*30}\n3.- Similitud (score >= 0.85)\n{"#"*30}\n')  
  
        update_analysis_run_status(request_id, "ANALYZING")  
  
        grupos_detectados = 0  
        group_id = 1  
  
        # Filtrar chunks por la categoría recibida en el URL  
        # Si producto == "ALL", analizar todo el inventario  
        anchors = [  
            c for c in chunks  
            if producto.upper() == "ALL"  
            or producto.upper() in (c["metadata"].get("CATEGORY_NAME") or "").upper()  
        ]  
  
        for chunk in anchors:  
            meta = chunk["metadata"]  
  
            candidatos = rag.buscar_y_persistir(  
                anchor      = meta,          # dict con ITEM_DESCRIPTION, CATEGORY_NAME, etc.  
                request_id  = request_id,  
                group_id    = group_id,  
                group_label = f"Grupo {group_id} — {meta.get('CATEGORY_NAME', '')}",  
                group_risk  = "medium",      # el LLM (propose_node) lo refinará después  
                top_k       = 10,  
                umbral      = 0.85,  
            )  
  
            if candidatos:  
                grupos_detectados += 1  
                group_id += 1  
  
        update_analysis_run_kpis(request_id, groups_detected=grupos_detectados)  
        update_analysis_run_status(request_id, "ANALYZED")  
  
        return {  
            "request_id":       request_id,  
            "items_total":      len(chunks),  
            "items_embedded":   insertados,  
            "groups_detected":  grupos_detectados,  
        }  
  
    except Exception as e:  
        # Registrar el error en inv_analysis_runs para poder reanudar  
        if request_id:  
            update_analysis_run_status(request_id, "ERROR")  
        raise HTTPException(status_code=500, detail=str(e))