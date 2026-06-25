from agent_services.app.tools.Tool import embedding_tool, similarity_tool
from agent_services.app.schemas.schemas import Embedding
from langchain_openai.chat_models import ChatOpenAI
from langchain.agents import create_agent
from dotenv import load_dotenv
import os

load_dotenv(override=True)

LLM_MODEL = os.getenv("LLM_MODEL")

llm = ChatOpenAI(LLM_MODEL, temperature=0)

rag_agent_prompt = """
    ### Eres un agente de IA especial que UNICAMENTE EJECUTA UN SERVICIO RAG

    ### Instrucciones:
    - Utiliza unicamente las funciones de la herramienta embedding_tool y similarity_tool para ejecutar el servicio RAG
    - Tu deber es vectorizar y buscar semánticamente los ítems de inventario
    - Tu deber es obtener los resultados de la búsqueda en formato JSON
"""

rag_agent = create_agent(
    model=llm,
    name="rag_agent",
    system_prompt=rag_agent_prompt,
    tools=[embedding_tool, similarity_tool],
    response_format=Embedding
)