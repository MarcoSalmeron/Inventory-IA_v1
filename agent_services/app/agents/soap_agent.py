from agent_services.app.tools.Tool import run_bulk_export
from agent_services.app.schemas.schemas import SOAPDownload
from langchain_openai.chat_models import ChatOpenAI
from langchain.agents import create_agent
from dotenv import load_dotenv
import os

load_dotenv(override=True)

LLM_MODEL = os.getenv("LLM_MODEL")

llm = ChatOpenAI(LLM_MODEL, temperature=0)

soap_agent_prompt = """
    ### Eres un agente de IA especial que UNICAMENTE EJECUTA UN SERVICIO SOAP

    ### Instrucciones:
    - Utiliza unicamente las funciones de la herramienta run_bulk_export para ejecutar el servicio SOAP
    - El servicio SOAP se encarga de extraer los datos de inventario de una empresa 
    -Tu deber es obtener el archivo ZIP de la extracción de inventario

    ### Formato de respuesta:
    - El archivo ZIP descargado
    - ID del request para la extracción
"""

soap_agent = create_agent(
    model=llm,
    name="soap_agent",
    system_prompt=soap_agent_prompt,
    tools=[run_bulk_export],
    response_format=SOAPDownload
)
