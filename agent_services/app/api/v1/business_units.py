import pandas as pd
import requests
from pprint import pprint
from agent_services.app.core.credentials_service import get_credential, get_rest_endpoint

def get_business_units(credential_name : str):
    try:
        
        api = get_rest_endpoint('business-units')
        credential = get_credential(credential_name)
        response = requests.get(api['uri'], auth=(
            credential["host"], 
            credential["user_password"]
            ))
        data = response.json()
        pprint(data['items'])
        return pd.DataFrame(data["items"])
    
    except Exception as ex:
        raise ex

