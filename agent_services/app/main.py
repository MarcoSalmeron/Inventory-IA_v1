from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from agent_services.app.api.routes import router
from agent_services.app.api.v1.business_units import get_business_units
from agent_services.app.api.v1.organizations import get_organizations
import uvicorn



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
    df = get_business_units()
    print(df)
    return {"Bussiness Units": df.to_json(orient="records")}

if __name__ == "__main__":
    uvicorn.run(services, host="0.0.0.0", port=8000)
