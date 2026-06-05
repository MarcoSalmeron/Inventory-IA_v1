import pandas as pd
import requests
import os

def get_business_units():
    endpoint = "https://enev-test.fa.us2.oraclecloud.com/fscmRestApi/resources/11.13.18.05/finBusinessUnitsLOV?onlyData=true"
    response = requests.get(endpoint, auth=(os.getenv("USUARIO"), os.getenv("CONTRA")))
    data = response.json()
    return pd.DataFrame(data["items"])

