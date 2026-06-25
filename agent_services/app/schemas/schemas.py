from pydantic import BaseModel, Field

class SOAPDownload(BaseModel):
    zip_path: str = Field(description="Ruta al archivo ZIP descargado")
    request_id: str = Field(description="ID del request para la extracción")

class Embedding(BaseModel):
    inventory_item_id: int = Field(description="ID del ítem")
    item_number: str = Field(description="Número del ítem")
    item_description: str = Field(description="Descripción del ítem")
    category_name: str = Field(description="Nombre de la categoría")
    item_status: str = Field(description="Estado del ítem")
    organization_code: str = Field(description="Código de la organización")
    business_unit_name: str = Field(description="Nombre de la unidad de negocio")
    primary_uom_val: str = Field(description="Unidad de medida primaria")
    almacenaje: str = Field(description="Almacenaje del ítem")
    origen: str = Field(description="Origen del ítem")
    tipo: str = Field(description="Tipo del ítem")
    description_raw: str = Field(description="Descripción del ítem sin normalización")
    description_normalized: str = Field(description="Descripción del ítem normalizada")
    composite_text: str = Field(description="Texto composite para vectorización")
    embedding: str = Field(description="Vector de la descripción del ítem")