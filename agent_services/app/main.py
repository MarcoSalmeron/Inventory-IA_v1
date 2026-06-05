from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from agent_services.app.api.routes import router
from api import get_business_units, get_organizations


services = FastAPI(
    title="Inventario IA",
    description="API de Inventario gestionado por agentes",
    version="1.0.0",
    docs_url="/swagger",
    openapi_url="/api-spec"
)


services.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])
# Incluir rutas de la API
services.include_router(router)


@services.get("/")
def read_root():
    data = get_business_units()
    return data
