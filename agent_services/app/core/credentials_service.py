import os  
from cryptography.fernet import Fernet  
from agent_services.app.core.db_conn import get_conn  
from dotenv import load_dotenv  

load_dotenv(override=True)
  
try:
    FERNET_KEY = os.environ.get("FERNET_KEY")

    if FERNET_KEY:
        print("Fernet Key encontrada")
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
    attribute5: str = None,  
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
            attribute1, attribute2, attribute3, attribute4, attribute5,  
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
            "attribute5":      row[13],  
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