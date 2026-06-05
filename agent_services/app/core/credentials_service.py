import os  
from cryptography.fernet import Fernet  
from agent_services.app.core.db_conn import get_conn  
  
FERNET_KEY = os.getenv("FERNET_KEY")
fernet = Fernet(FERNET_KEY.encode())  
  
  
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
            credential_name,  
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
    conn = get_conn()  
    cur = conn.cursor()  
    cur.execute(  
        """  
        SELECT credential_name, host, username, user_password, estatus,  
               created_by, created_at, updated_by, is_active,  
               attribute1, attribute2, attribute3, attribute4, attribute5  
        FROM OFC_CREDENTIALS  
        WHERE credential_name = %s AND is_active = TRUE  
        """,  
        (credential_name,),  
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