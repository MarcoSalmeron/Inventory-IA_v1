from agent_services.app.core.soap_service import export_bulk_data, get_ess_job_status, download_ess_job_execution_details
from agent_services.app.core.rag import InventoryEmbeddingsRAG
from langchain.tools import tool
from time import time

# ─────────────────────────────────────────────  
# Paso 1.- flujo completo de exportar y extraer inventario
# ─────────────────────────────────────────────  
@tool
def run_bulk_export(  
    enterprise_id: int,  
    poll_interval: int = 10,   # segundos entre cada consulta de status  
    max_retries: int = 10,     # máximo de intentos antes de timeout  
) -> dict:  
    """  
    Ejecuta el flujo completo:  
      1. exportBulkData       → requestId  
      2. getESSJobStatus      → polling hasta SUCCEEDED  
      3. downloadESSJobExecutionDetails → ZIP guardado en DOWNLOAD_DIR  
    Retorna el Path del ZIP descargado.  
    """  
    print(f'\n{"="*30} \n--run_bulk_export (ORQUESTADOR)--\n {"="*30}\n')

    # Paso 1 - RequestID
    request_id = export_bulk_data(enterprise_id)  
    print(f"\n[SOAP] exportBulkData completado → requestId: {request_id}\n")  
  
    # Paso 2 - Status  
    terminal_states = {'SUCCEEDED', 'ERROR', 'FAILED', 'CANCELLED', 'WARNING'}  
    for attempt in range(1, max_retries + 1):  
        status = get_ess_job_status(enterprise_id, request_id)  
        print(f"\n[SOAP] getESSJobStatus → {status} (intento {attempt}/{max_retries})\n")  
  
        if status == 'SUCCEEDED':  
            break  
        if status in terminal_states:  
            raise RuntimeError(f"El job {request_id} terminó con estado inesperado: {status}")  
  
        time.sleep(poll_interval)  
    else:  
        raise TimeoutError(f"El job {request_id} no completó en {max_retries} intentos")  
  
    # Paso 3 - ZIP
    zip_path = download_ess_job_execution_details(enterprise_id, request_id)  
    print(f"\n[SOAP] ZIP guardado en: {zip_path.resolve()}\n\n")  

    return {
        "request_id": request_id,
        "zip_path": zip_path
    }

# ─────────────────────────────────────────────  
# Paso 2.- Embeddings
# ─────────────────────────────────────────────  

rag = InventoryEmbeddingsRAG()

@tool
def embedding_tool(
    chunks: list,
    request_id: str
) -> int:
    """
    Normaliza, vectoriza y persiste en inv_embeddings.

    El composite_text es el texto exacto enviado al modelo:
    normalize(item_description) | category_name_sin_COSTO | almacenaje
    Se guarda para auditoría (permite reproducir el vector exacto — DDL).

    El índice compuesto (request_id, organization_code, category_name) se aprovecha
    al filtrar en buscar() → siempre pasar category_filter para usar el índice HNSW.

    ON CONFLICT (request_id, inventory_item_id) DO NOTHING:
    Si el ítem ya tiene embedding para este request_id, se omite silenciosamente.
    Para re-vectorizar, llamar primero a limpiar_embeddings(request_id).
    """
    insertados = rag.cargar_inv_embeddings(chunks, request_id)
    rag.cerrar()
    return insertados

# ─────────────────────────────────────────────  
# Paso 3.- Similitud Semantica
# ─────────────────────────────────────────────  
@tool 
def similarity_tool(
    producto_texto: str,
    request_id: str
) -> list[dict]:
    """
    Búsqueda semántica vectorizada con filtro previo obligatorio de categoría.

    Estrategia (alineada con comentarios del DDL):
    ─────────────────────────────────────────────
    1. Normalizar el texto de consulta y construir el MISMO composite que en inserción.
       CRÍTICO: Si la query no comparte el mismo espacio vectorial que los embeddings
       almacenados, los scores coseno serán sistemáticamente incorrectos.

    2. Filtrar SIEMPRE por request_id.
       Filtrar por category_name cuando esté disponible (DDL: "Siempre filtrar por
       request_id + category_name ANTES del VECTOR_SEARCH. Reduce N² → suma(ni²)").
       Esto aprovecha el índice compuesto idx_emb_request_cat_org.

    3. Ejecutar VECTOR_SEARCH con operador <=> (distancia coseno, DDL: vector_cosine_ops).
       El índice HNSW (idx_emb_hnsw_cosine) hace la búsqueda aproximada de vecinos.

    4. Aplicar boosts post-coseno (UOM / TIPO / ORIGEN) como describe el DDL.

    5. Filtrar candidatos por umbral final_score ≥ 0.85 (DDL: "Umbral mínimo para entrar al grupo").

        Parámetros:
            producto_texto    : Descripción del ítem que se consulta (anchor).
            request_id        : ID del análisis — filtra SIEMPRE (índice).
            categoria_origen  : CATEGORY_NAME del anchor — filtra antes del HNSW.
            uom_origen        : PRIMARY_UOM_VAL del anchor — boost +0.150.
            tipo_origen       : TIPO del anchor — boost +0.100.
            origen_origen     : ORIGEN del anchor — boost +0.050.
            almacenaje_origen : ALMACENAJE del anchor — incluido en composite de la query.
            top_k             : Candidatos a recuperar del VECTOR_SEARCH antes del umbral.
            umbral            : final_score mínimo para aceptar un candidato (default 0.85).

        Retorna:
            Lista de dicts con los campos de inv_similarity_results listos para persistir.
            Solo incluye candidatos con final_score >= umbral.
    """
    candidatos = rag.buscar(producto_texto, request_id)
    rag.cerrar()
    return candidatos