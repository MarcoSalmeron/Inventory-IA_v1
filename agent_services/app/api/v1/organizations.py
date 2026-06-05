import pandas as pd
import requests
import os

def get_organizations():
    endpoint = "https://enev-test.fa.us2.oraclecloud.com/fscmRestApi/resources/11.13.18.05/inventoryOrganizations?onlyData=true&q=ManagementBusinessUnitId=300000465216591&fields=OrganizationId,OrganizationCode,OrganizationName,Status,ManagementBusinessUnitId,LegalEntityId,LegalEntityName,MasterOrganizationCode,MasterOrganizationName,ItemDefinitionOrganizationCode,ItemDefinitionOrganizationName"
    response = requests.get(endpoint, auth=(os.getenv("USUARIO"), os.getenv("CONTRA")))
    data = response.json()
    return pd.DataFrame(data["items"])