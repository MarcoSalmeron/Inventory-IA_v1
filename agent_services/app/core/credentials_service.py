import os  
from cryptography.fernet import Fernet  
from agent_services.app.core.db_conn import get_conn  
from dotenv import load_dotenv  

load_dotenv(override=True)
  
try:
    print(f'\n{"#"*30}\n---- CREDENTIALS SERVICE ----\n{"#"*30}\n')

    conn = get_conn()

    if conn:
        print(f"\n{'='*30}\n-- Conexión a la BD exitosa --\n{'='*30}\n")
    else:
        raise Exception("Error al conectar a la base de datos")
    
    conn.close()
    
    FERNET_KEY = os.getenv("FERNET_KEY")

    if FERNET_KEY:
        print(f"\n{'='*30}\n-- Fernet Key encontrada --\n{'='*30}\n")
        print(f"Fernet Key: {FERNET_KEY[:5]}...")
    else:
        raise Exception("Fernet Key no encontrada")

    fernet = Fernet(FERNET_KEY.encode())

except Exception as ex:
    raise ex
  
def _encrypt(value: str) -> str:  
    return fernet.encrypt(value.encode()).decode()  
  
  
def _decrypt(value: str) -> str:  
    return fernet.decrypt(value.encode()).decode()  
  
  
def save_credential(  
    credential_name: str,  
    host: str,  
    username: str,  
    user_password: str,  
    estatus: str = "ACTIVE",  
    created_by: str = None,  
    attribute1: str = None,  
    attribute2: str = None,  
    attribute3: str = None,  
    attribute4: str = None,  
    attribute5: str = None
) -> dict:  
    conn = get_conn()  
    cur = conn.cursor()  
    cur.execute(  
        """  
        INSERT INTO OFC_CREDENTIALS (  
            credential_name, host, username, user_password, estatus,  
            created_by, attribute1, attribute2, attribute3, attribute4, attribute5  
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)  
        """,  
        (  
            credential_name.strip().lower(),
            _encrypt(host),  
            _encrypt(username),  
            _encrypt(user_password),  
            estatus,  
            created_by,  
            attribute1, attribute2, attribute3, attribute4, attribute5 
        ),  
    )  
    conn.commit()  
    cur.close()  
    conn.close()  
    return {"message": f"Credencial '{credential_name}' guardada correctamente"}  
  
  
def get_credential(credential_name: str) -> dict | None:  
    try:
        conn = get_conn()  
        cur = conn.cursor()  
        cur.execute(  
            """  
            SELECT credential_name, host, username, user_password, estatus,  
                created_by, created_at, updated_by, is_active,  
                attribute1, attribute2, attribute3, attribute4, attribute5  
            FROM OFC_CREDENTIALS  
            WHERE LOWER(credential_name) = %s AND is_active = TRUE
            """,  
            (credential_name.strip().lower(),),
        )  
        row = cur.fetchone()  
        cur.close()  
        conn.close()  
        if not row:  
            return None  
        return {  
            "credential_name": row[0],  
            "host":            _decrypt(row[1]),  
            "username":        _decrypt(row[2]),  
            "user_password":   _decrypt(row[3]),  
            "estatus":         row[4],  
            "created_by":      row[5],  
            "created_at":      str(row[6]),  
            "updated_by":      row[7],  
            "is_active":       row[8],  
            "attribute1":      row[9],  
            "attribute2":      row[10],  
            "attribute3":      row[11],  
            "attribute4":      row[12],  
            "attribute5":      row[13]
        } 
    except Exception as ex:  
        raise ex
    
def update_credential(credential_name: str, **kwargs) -> dict | None:  
    fields_to_encrypt = {"host", "username", "user_password"}  
    set_clauses = []  
    values = []  
  
    for key, value in kwargs.items():  
        if value is None:  
            continue  
        if key in fields_to_encrypt:  
            value = _encrypt(value)  
        set_clauses.append(f"{key} = %s")  
        values.append(value)  
  
    if not set_clauses:  
        return {"message": "No se proporcionaron campos para actualizar"}  
  
    values.append(credential_name.strip().lower())
    conn = get_conn()  
    cur = conn.cursor()  
    cur.execute(  
        f"UPDATE OFC_CREDENTIALS SET {', '.join(set_clauses)} WHERE LOWER(credential_name) = %s AND is_active = TRUE",  
        values,  
    )  
    updated = cur.rowcount  
    conn.commit()  
    cur.close()  
    conn.close()  
    if updated == 0:  
        return None  
    return {"message": f"Credencial '{credential_name}' actualizada correctamente"}

def delete_credential(credential_name: str) -> dict | None:  
    conn = get_conn()  
    cur = conn.cursor()  
    cur.execute(  
        "UPDATE OFC_CREDENTIALS SET is_active = FALSE WHERE LOWER(credential_name) = %s AND is_active = TRUE",
        (credential_name.strip().lower(),),
    )  
    deleted = cur.rowcount  
    conn.commit()  
    cur.close()  
    conn.close()  
    if deleted == 0:  
        return None  
    return {"message": f"Credencial '{credential_name}' eliminada correctamente"}

def activate_credential(credential_name: str) -> dict | None:  
    conn = get_conn()  
    cur = conn.cursor()  
    cur.execute(  
        "UPDATE OFC_CREDENTIALS SET is_active = TRUE WHERE LOWER(credential_name) = %s AND is_active = FALSE",
        (credential_name.strip().lower(),),
    )  
    activated = cur.rowcount  
    conn.commit()  
    cur.close()  
    conn.close()  
    if activated == 0:  
        return None  
    return {"message": f"Credencial '{credential_name}' activada correctamente"}

def get_rest_endpoint(endpoint_name: str) -> dict | None:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
        """
            SELECT 
                api_name,
                description,
                uri,
                estatus,
                created_by,
                created_at,
                updated_by,
                is_active,
                attribute1,
                attribute2,
                attribute3,
                attribute4,
                attribute5
            FROM OFC_REST_API
            WHERE LOWER(api_name) = %s
            AND is_active = TRUE
            LIMIT 1
        """,
        (endpoint_name.strip().lower(),)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        return {
            "api_name":    row[0],
            "description": row[1],
            "uri":         row[2],
            "estatus":     row[3],
            "created_by":  row[4],
            "created_at":  str(row[5]),
            "updated_by":  row[6],
            "is_active":   row[7],
            "attribute1":  row[8],
            "attribute2":  row[9],
            "attribute3":  row[10],
            "attribute4":  row[11],
            "attribute5":  row[12]
        }
    except Exception as ex:
        raise ex

def save_process_config(
    process_code: str,
    inv_organization_id: int,
) -> dict:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO fnd_process_config (
                process_code, inv_organization_id
            ) VALUES (%s, %s)
            """,
            (
                process_code.strip().upper(),
                inv_organization_id,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"message": f"Proceso '{process_code}' guardado correctamente"}
    except Exception as ex:
        raise ex

def get_process_config(process_code: str) -> dict | None:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 
                id_process,
                process_code,
                inv_organization_id,
                created_by,
                created_at,
                updated_by,
                is_active,
                attribute1,
                attribute2,
                attribute3,
                attribute4,
                attribute5
            FROM fnd_process_config
            WHERE LOWER(process_code) = %s
              AND is_active = TRUE
            LIMIT 1
            """,
            (process_code.strip().lower(),),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        return {
            "id_process": row[0],
            "process_code": row[1],
            "inv_organization_id": row[2],
            "created_by": row[3],
            "created_at": row[4],
            "updated_by": row[5],
            "is_active": row[6],
            "attribute1": row[7],
            "attribute2": row[8],
            "attribute3": row[9],
            "attribute4": row[10],
            "attribute5": row[11],
        }
    except Exception as ex:
        raise ex
    
def find_credential(enterprise_id: int) -> dict | None:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""

        SELECT c.HOST, c.USER_PASSWORD
        FROM FND_ENTERPRISES e
        JOIN OFC_CREDENTIALS c ON c.CREDENTIAL_ID = e.CREDENTIAL_ID 
        WHERE e.ENTERPRISE_ID = %s
        AND c.IS_ACTIVE = TRUE
        LIMIT 1
        """, (enterprise_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        return {
            "host": _decrypt(row[0]),
            "user_password": _decrypt(row[1])
        }
    except Exception as ex:
        raise ex
    
def get_process_config(enterprise_id: int) -> dict | None:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
        SELECT c.process_code, e.ENTERPRISE_CODE, c.attribute1
        FROM fnd_process_config c
        JOIN FND_ENTERPRISES e ON c.ENTERPRISE_ID = e.ENTERPRISE_ID
        WHERE e.ENTERPRISE_ID = %s
        AND c.is_active = TRUE
        LIMIT 1
        """, (enterprise_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        return {
            "process_code": row[0],
            "enterprise_code": row[1],
            "attribute1": row[2],
        }
    except Exception as ex:
        raise ex