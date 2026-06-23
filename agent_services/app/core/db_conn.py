import psycopg2
import os

# Credenciales
USER = os.getenv("POSTGRES_USER")
PASSWORD = os.getenv("POSTGRES_PASSWORD")
HOST = os.getenv("POSTGRES_HOST")
PORT = os.getenv("POSTGRES_PORT")
DB = os.getenv("POSTGRES_DB")
CONN_STRING = f"postgresql://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB}"

# Conectar a la base de datos
def get_conn():
    return psycopg2.connect(CONN_STRING)

# PRIMER PASO del Pipeline: Extraccion del inventario
def create_analysis_run(request_id: str, status: str = "EXTRACTING"):  
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