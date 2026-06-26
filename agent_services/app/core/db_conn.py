from dotenv import load_dotenv
import psycopg2
import os

load_dotenv(override=True)

# Credenciales
USER = os.getenv("POSTGRES_USER")
PASSWORD = os.getenv("POSTGRES_PASSWORD")
HOST = os.getenv("POSTGRES_HOST")
PORT = os.getenv("POSTGRES_PORT")
DB = os.getenv("POSTGRES_DB")
CONN_STRING = f"postgresql://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB}"

# Conectar a la base de datos
def get_conn():
    """Conexión a la base de datos."""
    return psycopg2.connect(CONN_STRING)

# PRIMER PASO del Pipeline: Extraccion del inventario
def create_analysis_run(
    request_id: str, 
    status: str = "EXTRACTING"
):  
    """Creacion de la tabla de resultados de extraccion."""
    conn = get_conn()  
    print(f'\n{"=" * 30}\n1.- Creating analysis run for request {request_id}\n{"=" * 30}\n')
    try:  
        with conn.cursor() as cur:  
            cur.execute("""  
                INSERT INTO inv_analysis_runs (request_id, status)  
                VALUES (%s, %s)  
                ON CONFLICT (request_id) DO NOTHING  
            """, (request_id, status))  
        conn.commit()  
    finally:  
        conn.close()  

# SEGUNDO PASO del Pipeline: Actualizacion de la tabla de resultados de extraccion
def update_analysis_run_org(  
    request_id: str,  
    organization_id: str,  
    organization_code: str,  
    business_unit_id: str,  
    business_unit_name: str,  
    status: str = "EXTRACTED",  
):  
    """Actualizacion de la tabla de resultados de extraccion."""
    conn = get_conn()  
    print(f'\n{"=" * 30}\n2.- Updating analysis run for request {request_id}\n{"=" * 30}\n')
    try:  
        with conn.cursor() as cur:  
            cur.execute("""  
                UPDATE inv_analysis_runs  
                SET organization_id    = %s,  
                    organization_code  = %s,  
                    business_unit_id   = %s,  
                    business_unit_name = %s,  
                    status             = %s,  
                    updated_at         = NOW()  
                WHERE request_id = %s  
            """, (organization_id, organization_code,  
                  business_unit_id, business_unit_name,  
                  status, request_id))  
        conn.commit()  
    finally:  
        conn.close()

# HELPER actualizacion simple del estado de la ejecucion
def update_analysis_run_status(
    request_id: str, 
    status: str
):  
    """Transición simple de estado para fases EMBEDDING, EMBEDDED, ANALYZING, ANALYZED.""" 
    conn = get_conn()  
    try:  
        with conn.cursor() as cur:  
            cur.execute("""  
                UPDATE inv_analysis_runs  
                SET status = %s, updated_at = NOW()  
                WHERE request_id = %s  
            """, (status, request_id))  
        conn.commit()  
    finally:  
        conn.close()

# HELPER actualizacion de KPIs
def update_analysis_run_kpis(  
    request_id: str,  
    items_total: int = None,  
    items_embedded: int = None,  
    groups_detected: int = None,  
):  
    """  
    Actualiza los KPI cards del prototipo pRes() en inv_analysis_runs.  
    Solo actualiza los campos que se pasan (los demás quedan intactos).  
    """  
    conn = get_conn()  
    try:  
        with conn.cursor() as cur:  
            cur.execute("""  
                UPDATE inv_analysis_runs  
                SET items_total     = COALESCE(%s, items_total),  
                    items_embedded  = COALESCE(%s, items_embedded),  
                    groups_detected = COALESCE(%s, groups_detected),  
                    updated_at      = NOW()  
                WHERE request_id = %s  
            """, (items_total, items_embedded, groups_detected, request_id))  
        conn.commit()  
    finally:  
        conn.close()