import pandas as pd
import requests
from pprint import pprint
from agent_services.app.core.credentials_service import get_credential


def get_organizations(credential_name: str):
    try:

        endpoint = "https://enev-test.fa.us2.oraclecloud.com/fscmRestApi/resources/11.13.18.05/inventoryOrganizations?onlyData=true&q=ManagementBusinessUnitId=300000465216591&fields=OrganizationId,OrganizationCode,OrganizationName,Status,ManagementBusinessUnitId,LegalEntityId,LegalEntityName,MasterOrganizationCode,MasterOrganizationName,ItemDefinitionOrganizationCode,ItemDefinitionOrganizationName"
        credential = get_credential(credential_name)
        response = requests.get(endpoint, auth=(
            credential["username"], 
            credential["user_password"]
            ))
        data = response.json()
        pprint(data['items'])
        return pd.DataFrame(data["items"])
    
    except Exception as ex:
        raise ex
    