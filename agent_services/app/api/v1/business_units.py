import pandas as pd
import requests
import os
from dotenv import load_dotenv
from pprint import pprint
from agent_services.app.core.credentials_service import get_credential

load_dotenv(override=True)

def get_business_units(credential_name : str):
    try:
        endpoint = "https://enev-test.fa.us2.oraclecloud.com/fscmRestApi/resources/11.13.18.05/finBusinessUnitsLOV?onlyData=true"
        credential = get_credential(credential_name)
        user = credential["username"]
        password = credential["user_password"]
        response = requests.get(endpoint, auth=(user, password))
        data = response.json()
        pprint(data['items'])
        return pd.DataFrame(data["items"])
    except Exception as ex:
        raise ex

