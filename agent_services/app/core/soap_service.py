import base64  
import os  
import time  
import requests  
import xml.etree.ElementTree as ET  
from pathlib import Path  
from agent_services.app.core.credentials_service import get_credential, get_rest_endpoint  
from requests_toolbelt.multipart import decoder
from dotenv import load_dotenv

load_dotenv(override=True)

try:
    print(f'\n{"#"*30}\n---- SOAP SERVICE ----\n{"#"*30}\n')

    DOWNLOAD_DIR = Path(os.getenv("SOAP_DOWNLOAD_DIR", "downloads"))  

    if DOWNLOAD_DIR:
        print(f"\n{'='*30}\n-- Directorio de descarga encontrado --\n{'='*30}\n")
        print(f"Directorio de descarga: {DOWNLOAD_DIR.resolve()}")
    else:
        raise Exception("Directorio de descarga no encontrado")
  
    api = get_rest_endpoint('soap-erp-integration')
    
    if api:
        print(f"\n{'='*30}\n-- URI HTTP para SOAP encontrado --\n{'='*30}\n")
        print(f"URI: {api['uri']}\n\n")
    else:
        raise Exception("HTTP para SOAP no encontrado")
        
except Exception as ex:
    raise ex

# namespaces del SoapUI project  
NS = {
    'env': 'http://schemas.xmlsoap.org/soap/envelope/',
    'wsa': 'http://www.w3.org/2005/08/addressing',
    'ns0': 'http://xmlns.oracle.com/apps/financials/commonModules/shared/model/erpIntegrationService/',
    'ns2': 'http://xmlns.oracle.com/apps/financials/commonModules/shared/model/erpIntegrationService/types/',
    'ns1': 'http://xmlns.oracle.com/adf/svc/types/',
    'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
    'xop': 'http://www.w3.org/2004/08/xop/include',
}


  
def _soap_headers(action: str) -> dict:  
    return {  
        "Content-Type": "text/xml; charset=utf-8",  
        "SOAPAction": action, 
    }  
  
def _parse_xml(xml_str: str, xpath: str) -> str | None:  
    """Extraer texto de un tag en la respuesta SOAP"""  
    root = ET.fromstring(xml_str)  
    el = root.find(xpath, NS)  
    return el.text if el is not None else None  
  
# ─────────────────────────────────────────────  
# 1. exportBulkData → retorna requestId  
# ─────────────────────────────────────────────  
def export_bulk_data(credential_name: str, **kwargs) -> str:
    print(f'\n{"="*30}\n-- iniciando exportBulkData --\n{"="*30}\n')

    api = get_rest_endpoint('soap-erp-integration')
    credential = get_credential(credential_name)

    envelope = f"""
    <soapenv:Envelope
        xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:typ="http://xmlns.oracle.com/apps/financials/commonModules/shared/model/erpIntegrationService/types/">
   <soapenv:Header/>
   <soapenv:Body>
      <typ:exportBulkData>
         <typ:jobName>{kwargs.get('job_name', '/oracle/apps/ess/custom/Integration/INV/Catalogos/,INT_JOB_ALL_INV_ITEMS_EXTRACT')}</typ:jobName>
         <typ:parameterList>{kwargs.get('parameter_list', '')}</typ:parameterList>
         <typ:jobOptions>{kwargs.get('job_options', 'ExtractFileType=ALL')}</typ:jobOptions>
         <typ:callbackURL>{kwargs.get('callback_url', '')}</typ:callbackURL>
         <typ:notificationCode>{kwargs.get('notification_code', '12')}</typ:notificationCode>
      </typ:exportBulkData>
    </soapenv:Body>
    </soapenv:Envelope>"""

    response = requests.post(
        api['uri'],
        data=envelope.encode('utf-8'),
        headers=_soap_headers(
            "http://xmlns.oracle.com/apps/financials/commonModules/shared/model/erpIntegrationService/ErpIntegrationService/exportBulkData"
        ),
        auth=(credential['host'], credential['user_password']),
    )

    response.raise_for_status()

    print(f"\n{'='*30}\n--exportBulkData Status Code--\n{'='*30}\n")
    print(response.status_code)

    request_id = _parse_xml(
        response.text,
        f".//ns2:exportBulkDataResponse/{{{NS['ns2']}}}result"
    )

    if not request_id:
        raise ValueError(f"No se obtuvo requestId. Respuesta:\n{response.text}")
    else:
        print(f"\n{'='*30}\n--exportBulkData finalizado--\n{'='*30}\n")
        print(f"requestId: {request_id}")

    return request_id

  
  
# ─────────────────────────────────────────────  
# 2. getESSJobStatus → WAIT | RUNNING | SUCCEEDED  
# ─────────────────────────────────────────────  
def get_ess_job_status(credential_name: str, request_id: str) -> str:
    print(f'\n{"="*30}\n-- iniciando getESSJobStatus --\n{"="*30}\n')

    api = get_rest_endpoint('soap-erp-integration')
    credential = get_credential(credential_name)

    envelope = f"""
    <soapenv:Envelope
        xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:typ="http://xmlns.oracle.com/apps/financials/commonModules/shared/model/erpIntegrationService/types/">
       <soapenv:Header/>
       <soapenv:Body>
          <typ:getESSJobStatus>
             <typ:requestId>{request_id}</typ:requestId>
          </typ:getESSJobStatus>
       </soapenv:Body>
    </soapenv:Envelope>"""

    response = requests.post(
        api['uri'],
        data=envelope.encode('utf-8'),
        headers=_soap_headers(
            "http://xmlns.oracle.com/apps/financials/commonModules/shared/model/erpIntegrationService/ErpIntegrationService/getESSJobStatus"
        ),
        auth=(credential['host'], credential['user_password']),
    )

    response.raise_for_status()

    print(f"\n{'='*30}\n--getESSJobStatus Status Code--\n{'='*30}\n")
    print(response.status_code)

    status = _parse_xml(
        response.text,
        f".//ns2:getESSJobStatusResponse/{{{NS['ns2']}}}result"
    )

    if not status:
        raise ValueError(f"No se obtuvo status. Respuesta:\n{response.text}")
    else:
        print(f"\n{'='*30}\n--getESSJobStatus finalizado--\n{'='*30}\n")
        print(f"status: {status.upper()}")
        print(f"requestId: {request_id}")

    return status.upper()

  
  
# ─────────────────────────────────────────────  
# 3. downloadESSJobExecutionDetails → ZIP local  
# ─────────────────────────────────────────────  
def download_ess_job_execution_details(credential_name: str, request_id: str) -> Path:
    print(f'\n{"="*30} \n-- iniciando downloadESSJobExecutionDetails (ZIP) --\n {"="*30}\n')

    api = get_rest_endpoint('soap-erp-integration')
    credential = get_credential(credential_name)

    envelope = f"""
    <soapenv:Envelope
        xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:typ="http://xmlns.oracle.com/apps/financials/commonModules/shared/model/erpIntegrationService/types/">
   <soapenv:Header/>
   <soapenv:Body>
      <typ:downloadESSJobExecutionDetails>
         <typ:requestId>{request_id}</typ:requestId>
      </typ:downloadESSJobExecutionDetails>
   </soapenv:Body>
    </soapenv:Envelope>"""

    response = requests.post(
        api['uri'],
        data=envelope.encode('utf-8'),
        headers=_soap_headers(
            "http://xmlns.oracle.com/apps/financials/commonModules/shared/model/erpIntegrationService/ErpIntegrationService/downloadESSJobExecutionDetails"
        ),
        auth=(credential['host'], credential['user_password']),
    )
    response.raise_for_status()

    print(f"\n{'='*30}\n--downloadESSJobExecutionDetails Status Code--\n{'='*30}\n")
    print(response.status_code)

    content_type = response.headers.get('Content-Type', '')
    zip_bytes = None

    # 1) MTOM / multipart/related
    if 'multipart/related' in content_type:
        mp = decoder.MultipartDecoder(response.content, content_type)
        xml_part = None
        attachments = {}
        for part in mp.parts:
            # headers son bytes; normalizamos
            headers = {k.decode().lower(): v.decode() for k, v in part.headers.items()}
            ctype = headers.get('content-type', '')
            cid = headers.get('content-id', '').strip()
            # guardar attachments por content-id sin <>
            if cid:
                cid_clean = cid.strip('<>')
                attachments[cid_clean] = part.content
            # identificar la parte XML (application/xop+xml o text/xml)
            if 'xml' in ctype:
                xml_part = part.content.decode('utf-8')

        if not xml_part:
            raise ValueError("No se encontró la parte XML en la respuesta MTOM.")

        # parsear XML y obtener href del xop:Include
        ET.register_namespace('xop', 'http://www.w3.org/2004/08/xop/include')
        root = ET.fromstring(xml_part)
        include = root.find('.//{http://www.w3.org/2004/08/xop/include}Include')
        if include is None:
            # alternativa: buscar por cualquier Include con ese namespace
            includes = root.findall('.//{http://www.w3.org/2004/08/xop/include}Include')
            include = includes[0] if includes else None
        if include is None:
            raise ValueError("No se encontró xop:Include en el XML de la parte XML.")

        href = include.attrib.get('href', '')
        if not href.startswith('cid:'):
            raise ValueError(f"href inesperado en xop:Include: {href}")
        cid_ref = href[len('cid:'):]
        if cid_ref not in attachments:
            # intentar con variantes (algunas implementaciones usan <> en Content-ID)
            alt_keys = [k.strip('<>') for k in attachments.keys()]
            if cid_ref not in alt_keys:
                raise ValueError(f"Attachment con Content-ID {cid_ref} no encontrado.")
        zip_bytes = attachments[cid_ref]

    else:
        # 2) Fallback: resultado en base64 dentro del XML
        b64_content = _parse_xml(
            response.text,
            f".//ns2:downloadESSJobExecutionDetailsResponse/{{{NS['ns2']}}}result"
        )
        if not b64_content:
            raise ValueError(f"No se obtuvo contenido ZIP. Respuesta:\n{response.text}")
        zip_bytes = base64.b64decode(b64_content)

    # escribir archivo
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DOWNLOAD_DIR / f"ess_job_{request_id}.zip"
    output_path.write_bytes(zip_bytes)

    if output_path.exists():
        print(f"\n{'='*30}\n-- downloadESSJobExecutionDetails finalizado --\n{'='*30}\n")
        print(f"Archivo guardado en: {output_path.resolve()}")
    else:
        raise RuntimeError(f"No se pudo guardar el archivo en {output_path.resolve()}")
    
    return output_path
  
  
# ─────────────────────────────────────────────  
# Orquestador: flujo completo  
# ─────────────────────────────────────────────  
def run_bulk_export(  
    credential_name: str,  
    poll_interval: int = 10,   # segundos entre cada consulta de status  
    max_retries: int = 60,     # máximo de intentos antes de timeout  
    **kwargs  
) -> Path:  
    """  
    Ejecuta el flujo completo:  
      1. exportBulkData       → requestId  
      2. getESSJobStatus      → polling hasta SUCCEEDED  
      3. downloadESSJobExecutionDetails → ZIP guardado en DOWNLOAD_DIR  
    Retorna el Path del ZIP descargado.  
    """  
    print(f'\n{"="*10} \n--run_bulk_export (ORQUESTADOR)--\n {"="*10}\n')

    # Paso 1 - RequestID
    request_id = export_bulk_data(credential_name, **kwargs)  
    print(f"[SOAP] exportBulkData completado → requestId: {request_id}")  
  
    # Paso 2 - Status  
    terminal_states = {'SUCCEEDED', 'ERROR', 'FAILED', 'CANCELLED', 'WARNING'}  
    for attempt in range(1, max_retries + 1):  
        status = get_ess_job_status(credential_name, request_id)  
        print(f"[SOAP] getESSJobStatus → {status} (intento {attempt}/{max_retries})")  
  
        if status == 'SUCCEEDED':  
            break  
        if status in terminal_states:  
            raise RuntimeError(f"El job {request_id} terminó con estado inesperado: {status}")  
  
        time.sleep(poll_interval)  
    else:  
        raise TimeoutError(f"El job {request_id} no completó en {max_retries} intentos")  
  
    # Paso 3 - ZIP
    zip_path = download_ess_job_execution_details(credential_name, request_id)  
    print(f"[SOAP] ZIP guardado en: {zip_path.resolve()}")  

    return zip_path