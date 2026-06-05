# ---- Base image ----
FROM python:3.12

# ---- Variables de entorno ----
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ---- Directorio de trabajo ----
WORKDIR /app

# ---- Copiar dependencias primero (mejora cache) ----
COPY requirements.txt .

# ---- Instalar dependencias Python ----
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ---- Copiar SOLO el contenido de agent_services/app/ ----
COPY  agent_services/ agent_services/

# ---- Exponer puerto ----
EXPOSE 8000

# ---- Comando de arranque ----
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "agent_services.app.main:services", "--bind", "0.0.0.0:8000", "--workers", "2"]