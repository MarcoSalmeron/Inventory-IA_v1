import pandas as pd
import re
import requests
from pprint import pprint
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from agent_services.app.core.credentials_service import find_credential, get_rest_endpoint, get_process_config

def get_organizations(enterprise_id: int, management_business_unit_id: str = None):  
    try:  

        api = get_rest_endpoint('organizations')  
        credential = find_credential(enterprise_id)  
  
        uri = api['uri']  
  
        if management_business_unit_id:  
            parsed = urlparse(uri)  
            params = parse_qs(parsed.query, keep_blank_values=True)  
  
            # Reemplazar parametro 'q' = "ManagementBusinessUnitId"  
            q_value = params.get('q', [''])[0]  
            new_q = re.sub(  
                r'ManagementBusinessUnitId=\d+',  
                f'ManagementBusinessUnitId={management_business_unit_id}',  
                q_value  
            )  
            # Filtrar por nuevo BusinessUnitID
            params['q'] = [new_q]  
  
            new_query = urlencode(params, doseq=True)  
            uri = urlunparse(parsed._replace(query=new_query))  
  
        response = requests.get(uri, auth=(  
            credential["host"],  
            credential["user_password"]  
        ))  
        data = response.json()  
        pprint(data['items'])  
        return pd.DataFrame(data["items"])  
  
    except Exception as ex:  
        raise ex
    
def get_organizationId(enterprise_id: int, position: int = 0):
    try:  

        api = get_rest_endpoint('organizations')  
        credential = find_credential(enterprise_id)  
  
        uri = api['uri']  

        management_business_unit_id = get_process_config(enterprise_id)

        management_business_unit_id = management_business_unit_id['enterprise_code']
  
        if management_business_unit_id:  
            parsed = urlparse(uri)  
            params = parse_qs(parsed.query, keep_blank_values=True)  
  
            # Reemplazar parametro 'q' = "ManagementBusinessUnitId"  
            q_value = params.get('q', [''])[0]  
            new_q = re.sub(  
                r'ManagementBusinessUnitId=\d+',  
                f'ManagementBusinessUnitId={management_business_unit_id}',  
                q_value  
            )  
            # Filtrar por nuevo BusinessUnitID
            params['q'] = [new_q]  
  
            new_query = urlencode(params, doseq=True)  
            uri = urlunparse(parsed._replace(query=new_query))  
  
        response = requests.get(uri, auth=(  
            credential["host"],  
            credential["user_password"]  
        ))  
        data = response.json()  
        pprint(data['items'])  
        return data["items"][position]['OrganizationId']

    except Exception as ex:
        raise ex