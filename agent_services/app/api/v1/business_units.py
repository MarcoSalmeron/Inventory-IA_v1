import pandas as pd
import requests
import os
from dotenv import load_dotenv

load_dotenv(override=True)

def get_business_units():
    try:
        endpoint = "https://enev-test.fa.us2.oraclecloud.com/fscmRestApi/resources/11.13.18.05/finBusinessUnitsLOV?onlyData=true"
        response = requests.get(endpoint, auth=(os.getenv("USUARIO"), os.getenv("CONTRA")))
        data = response.json()
        print(data)
        return pd.DataFrame(data["items"])
    except Exception as ex:
        raise ex

