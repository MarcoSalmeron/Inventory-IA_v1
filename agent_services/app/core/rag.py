import json
import re
import os
import sys
import io
import warnings
from statistics import mean
from sentence_transformers import SentenceTransformer
from agent_services.app.core.db_conn import get_conn
from dotenv import load_dotenv

load_dotenv(override=True)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE ENTORNO
# ─────────────────────────────────────────────────────────────────────────────
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

MODELO_EMBEDDING = os.getenv("HF_MODEL")

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES DE BOOST
# Deben coincidir exactamente con las definidas en el DDL de inv_similarity_results:
#   uom_boost   → +0.150 si mismo PRIMARY_UOM_VAL
#   tipo_boost  → +0.100 si mismo TIPO
#   origen_boost→ +0.050 si mismo ORIGEN
#   cosine_weight → 0.70 (peso del score semántico en la ponderación final)
#   UMBRAL_SIMILITUD → 0.85 mínimo para que un candidato entre a un grupo
# ─────────────────────────────────────────────────────────────────────────────
UOM_BOOST       = 0.150
TIPO_BOOST      = 0.100
ORIGEN_BOOST    = 0.050
COSINE_WEIGHT   = 0.70
UMBRAL_SIMILITUD = 0.85  # final_score mínimo para pertenecer al grupo (DDL: "≥ 0.85 para entrar")

# ─────────────────────────────────────────────────────────────────────────────
# PREFIJOS A ELIMINAR EN LA NORMALIZACIÓN
# El DDL menciona explícitamente: "sin prefijos ALI./LIM./EMB."
# ─────────────────────────────────────────────────────────────────────────────
PREFIJOS_ELIMINAR = re.compile(
    r"^\s*(ALI|LIM|EMB|COSTO|MAT|SER|CONS|PROD|SERV)\s*[./\-]\s*",
    re.IGNORECASE
)

# Cantidades numéricas con unidad al inicio o dentro de la descripción
# Ej: "1 KG HARINA", "500ML AGUA" → "HARINA", "AGUA"
CANTIDADES_RE = re.compile(r"\b\d+(\.\d+)?\s*(KG|GR|G|ML|LT|L|PZ|UN|CM|MM|M|TON)\b", re.IGNORECASE)

# Stop words básicas para inventario en español
STOP_WORDS = {
    "de", "la", "el", "en", "y", "a", "para", "con", "por", "del",
    "los", "las", "un", "una", "es", "se", "no", "al", "lo", "su"
}

# ─────────────────────────────────────────────────────────────────────────────
# CLASE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────
class InventoryEmbeddingsRAG:
    """
    RAG de búsqueda semántica vectorizada para inventario.

    Flujo principal:
        1. cargar_inv_embeddings()  → normaliza + vectoriza + persiste en inv_embeddings
        2. buscar()                 → vectoriza la consulta con el MISMO composite,
                                      aplica VECTOR_SEARCH con <=> (coseno),
                                      filtra SIEMPRE por request_id + category_name (índice HNSW),
                                      aplica boosts post-coseno (UOM / TIPO / ORIGEN),
                                      filtra por UMBRAL_SIMILITUD ≥ 0.85,
                                      persiste grupos en inv_similarity_results.

    Acoplamiento con DDLs:
        - inv_embeddings:         VECTOR(768), índice HNSW (m=16, ef_construction=64),
                                  índice compuesto (request_id, organization_code, category_name).
        - inv_similarity_results: grupo con is_anchor / candidatos, workflow de aprobación,
                                  group_avg_score calculado sobre todos los candidatos del grupo.
    """

    def __init__(self):
        print(f"\n{'=' * 60}\n[RAG] Cargando modelo all-mpnet-base-v2 (768 d)...\n{'=' * 60}\n")
        self.model = SentenceTransformer(MODELO_EMBEDDING)
        self.conn = get_conn()
        print(f"\n{'=' * 60}\n[OK] Modelo cargado: {MODELO_EMBEDDING}\n{'=' * 60}\n")

    # ─────────────────────────────────────────────────────────────────────────
    # NORMALIZACIÓN TEXTUAL
    # Según DDL: "sin prefijos ALI./LIM./EMB., cantidades, stop words"
    # El composite guarda exactamente lo que el modelo vio — permite reproducir
    # el vector para auditoría (comentario DDL inv_embeddings.composite_text).
    # ─────────────────────────────────────────────────────────────────────────
    def _limpiar_encoding(self, texto: str) -> str:
        """Corrige caracteres corruptos de doble-encoding latin-1/utf-8."""
        if not texto:
            return ""
        try:
            texto = texto.encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass

        reemplazos = {
            "Ã³": "ó", "Ã©": "é", "Ã¡": "á", "Ã­": "í", "Ãº": "ú",
            "Ã±": "ñ", "Ã'": "Ñ", "Â¿": "¿", "Â¡": "¡",
            "Ã ": "à", "Ã¼": "ü", "â€™": "'", "â€œ": '"', "â€": '"',
        }
        for corrupto, correcto in reemplazos.items():
            texto = texto.replace(corrupto, correcto)
        return texto

    def _normalizar_descripcion(self, texto: str) -> str:
        """
        Normalización completa alineada al DDL (campo description_normalized):
          1. Limpieza de encoding.
          2. Strip de prefijos ALI./LIM./EMB. y similares.
          3. Eliminación de cantidades numéricas con unidad (1KG, 500ML…).
          4. Lowercase y strip de stop words.
          5. Colapso de espacios múltiples.
        """
        if not texto:
            return ""
        texto = self._limpiar_encoding(texto)
        texto = PREFIJOS_ELIMINAR.sub("", texto)
        texto = CANTIDADES_RE.sub(" ", texto)
        tokens = texto.lower().split()
        tokens = [t for t in tokens if t not in STOP_WORDS and len(t) > 1]
        return " ".join(tokens).strip()

    def _construir_composite(
        self,
        descripcion_norm: str,
        categoria: str,
        almacenaje: str,
    ) -> str:
        """
        Construye el composite_text exactamente según el DDL:
            normalize(item_description) + category_name_sin_COSTO + almacenaje

        El DDL indica que la categoría se incluye SIN el prefijo "COSTO".
        El composite es el texto que se envía al modelo y se guarda para auditoría.

        CRÍTICO: Este mismo método debe usarse tanto al insertar (cargar_inv_embeddings)
        como al buscar (buscar), para garantizar que query y vectores almacenados
        pertenezcan al mismo espacio semántico.
        """
        categoria_clean = re.sub(r"\bCOSTO\b", "", categoria or "", flags=re.IGNORECASE).strip(" |-_")
        partes = [p for p in [descripcion_norm, categoria_clean, almacenaje] if p]
        return " | ".join(partes)

    # ─────────────────────────────────────────────────────────────────────────
    # VECTORIZACIÓN
    # normalize_embeddings=True → L2=1 → operador <=> equivale a distancia coseno
    # (comentario DDL inv_embeddings.embedding)
    # ─────────────────────────────────────────────────────────────────────────
    def _vectorizar(self, texto: str) -> str:
        """
        Genera embedding normalizado y lo serializa al formato aceptado por pgvector.
        normalize_embeddings=True garantiza que <=> sea equivalente a distancia coseno.
        """
        vec = self.model.encode(texto, normalize_embeddings=True)
        return json.dumps(vec.tolist())

    # ─────────────────────────────────────────────────────────────────────────
    # CÁLCULO DE SCORE
    # Fórmula exacta del DDL (inv_similarity_results.final_score):
    #   final_score = cosine×0.70 + uom_boost + tipo_boost + origen_boost
    # Máximo teórico: 0.70 + 0.15 + 0.10 + 0.05 = 1.00
    # ─────────────────────────────────────────────────────────────────────────
    def _calcular_score(
        self,
        cosine_score: float,
        cand_uom: str,
        cand_tipo: str,
        cand_origen: str,
        uom_origen: str | None,
        tipo_origen: str | None,
        origen_origen: str | None,
    ) -> dict:
        """
        Aplica la ponderación post-coseno definida en el DDL.
        Retorna dict con todos los componentes del score para persistirlos.
        """
        uom_b    = UOM_BOOST    if (uom_origen    and cand_uom    == uom_origen)    else 0.0
        tipo_b   = TIPO_BOOST   if (tipo_origen   and cand_tipo   == tipo_origen)   else 0.0
        origen_b = ORIGEN_BOOST if (origen_origen and cand_origen == origen_origen) else 0.0
        final    = round((cosine_score * COSINE_WEIGHT) + uom_b + tipo_b + origen_b, 4)
        return {
            "cosine_score": round(cosine_score, 4),
            "uom_boost":    round(uom_b,    3),
            "tipo_boost":   round(tipo_b,   3),
            "origen_boost": round(origen_b, 3),
            "final_score":  final,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # GESTIÓN DE LA TABLA inv_embeddings
    # ─────────────────────────────────────────────────────────────────────────
    def limpiar_embeddings(self, request_id: str) -> None:
        """
        Elimina embeddings de un request_id específico.
        ON DELETE CASCADE en inv_embeddings → también limpia inv_similarity_results.

        CORRECCIÓN vs versión anterior: filtra SIEMPRE por request_id
        para no borrar análisis históricos de otros request_ids.
        """
        print(f"\n{'=' * 60}\n[DB] Limpiando embeddings para request_id={request_id}\n{'=' * 60}\n")
        cur = self.conn.cursor()
        cur.execute("DELETE FROM inv_embeddings WHERE request_id = %s", [request_id])
        eliminados = cur.rowcount
        self.conn.commit()
        cur.close()
        print(f"\n[DB] {eliminados} embeddings eliminados para request_id={request_id}\n")

    def cargar_inv_embeddings(self, chunks: list, request_id: str) -> int:
        """
        Normaliza, vectoriza y persiste en inv_embeddings.

        El composite_text es el texto exacto enviado al modelo:
            normalize(item_description) | category_name_sin_COSTO | almacenaje
        Se guarda para auditoría (permite reproducir el vector exacto — DDL).

        El índice compuesto (request_id, organization_code, category_name) se aprovecha
        al filtrar en buscar() → siempre pasar category_filter para usar el índice HNSW.

        ON CONFLICT (request_id, inventory_item_id) DO NOTHING:
        Si el ítem ya tiene embedding para este request_id, se omite silenciosamente.
        Para re-vectorizar, llamar primero a limpiar_embeddings(request_id).
        """
        print(f"\n{'=' * 60}\n[DB] Vectorizando e insertando {len(chunks)} chunks — request_id={request_id}\n{'=' * 60}\n")
        cur = self.conn.cursor()
        insertados = 0

        for chunk in chunks:
            meta = chunk["metadata"]
            descripcion_raw  = meta.get("ITEM_DESCRIPTION", "") or ""
            descripcion_norm = self._normalizar_descripcion(descripcion_raw)
            categoria        = meta.get("CATEGORY_NAME",   "") or ""
            almacenaje       = meta.get("ALMACENAJE",      "") or ""

            # ── Composite: mismo método que en buscar() para garantizar simetría ──
            composite = self._construir_composite(descripcion_norm, categoria, almacenaje)
            if not composite:
                print(f"  [SKIP] Item sin texto válido: {meta.get('INVENTORY_ITEM_ID')}")
                continue

            vector_str = self._vectorizar(composite)

            cur.execute("""
                INSERT INTO inv_embeddings (
                    request_id,         embedding_model,    embedding_dimensions,
                    inventory_item_id,  organization_code,  business_unit_name,
                    category_name,      item_number,        item_status,
                    primary_uom_val,    almacenaje,         origen,             tipo,
                    description_raw,    description_normalized,  composite_text,
                    embedding
                )
                VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s::vector
                )
                ON CONFLICT (request_id, inventory_item_id) DO NOTHING
            """, [
                request_id,                         MODELO_EMBEDDING,               768,
                meta.get("INVENTORY_ITEM_ID"),      meta.get("ORGANIZATION_CODE"),  meta.get("BUSINESS_UNIT_NAME"),
                categoria,                          meta.get("ITEM_NUMBER"),         meta.get("ITEM_STATUS"),
                meta.get("PRIMARY_UOM_VAL"),        almacenaje,                     meta.get("ORIGEN"),             meta.get("TIPO"),
                descripcion_raw,                    descripcion_norm,               composite,
                vector_str,
            ])
            insertados += 1

        self.conn.commit()
        cur.close()
        print(f"\n[OK] {insertados} embeddings insertados en inv_embeddings.\n")
        return insertados

    # ─────────────────────────────────────────────────────────────────────────
    # BÚSQUEDA SEMÁNTICA VECTORIZADA
    # ─────────────────────────────────────────────────────────────────────────
    def buscar(
        self,
        producto_texto: str,
        request_id: str,
        categoria_origen: str | None = None,
        uom_origen: str | None = None,
        tipo_origen: str | None = None,
        origen_origen: str | None = None,
        almacenaje_origen: str | None = None,
        top_k: int = 10,
        umbral: float = UMBRAL_SIMILITUD,
    ) -> list[dict]:
        """
        Búsqueda semántica vectorizada con filtro previo obligatorio de categoría.

        Estrategia (alineada con comentarios del DDL):
        ─────────────────────────────────────────────
        1. Normalizar el texto de consulta y construir el MISMO composite que en inserción.
           CRÍTICO: Si la query no comparte el mismo espacio vectorial que los embeddings
           almacenados, los scores coseno serán sistemáticamente incorrectos.

        2. Filtrar SIEMPRE por request_id.
           Filtrar por category_name cuando esté disponible (DDL: "Siempre filtrar por
           request_id + category_name ANTES del VECTOR_SEARCH. Reduce N² → suma(ni²)").
           Esto aprovecha el índice compuesto idx_emb_request_cat_org.

        3. Ejecutar VECTOR_SEARCH con operador <=> (distancia coseno, DDL: vector_cosine_ops).
           El índice HNSW (idx_emb_hnsw_cosine) hace la búsqueda aproximada de vecinos.

        4. Aplicar boosts post-coseno (UOM / TIPO / ORIGEN) como describe el DDL.

        5. Filtrar candidatos por umbral final_score ≥ 0.85 (DDL: "Umbral mínimo para
           entrar al grupo").

        Parámetros:
            producto_texto    : Descripción del ítem que se consulta (anchor).
            request_id        : ID del análisis — filtra SIEMPRE (índice).
            categoria_origen  : CATEGORY_NAME del anchor — filtra antes del HNSW.
            uom_origen        : PRIMARY_UOM_VAL del anchor — boost +0.150.
            tipo_origen       : TIPO del anchor — boost +0.100.
            origen_origen     : ORIGEN del anchor — boost +0.050.
            almacenaje_origen : ALMACENAJE del anchor — incluido en composite de la query.
            top_k             : Candidatos a recuperar del VECTOR_SEARCH antes del umbral.
            umbral            : final_score mínimo para aceptar un candidato (default 0.85).

        Retorna:
            Lista de dicts con los campos de inv_similarity_results listos para persistir.
            Solo incluye candidatos con final_score >= umbral.
        """
        print(f"\n{'=' * 60}\n[RAG] Búsqueda semántica: '{producto_texto}'\n"
              f"      Categoría: {categoria_origen} | UOM: {uom_origen} | top_k: {top_k}\n{'=' * 60}\n")

        # ── 1. Construir composite de la query con el MISMO método que la inserción ──
        descripcion_norm = self._normalizar_descripcion(producto_texto)
        composite_query  = self._construir_composite(
            descripcion_norm,
            categoria_origen or "",
            almacenaje_origen or "",
        )
        emb_str = self._vectorizar(composite_query)

        cur = self.conn.cursor()

        # ── 2. Query con filtro pre-HNSW por request_id + category_name ──────────────
        # El índice idx_emb_request_cat_org (request_id, organization_code, category_name)
        # reduce el espacio de búsqueda ANTES de invocar el índice HNSW.
        # DDL: "Siempre filtrar por request_id + category_name antes de usar el índice HNSW."
        query = """
            SELECT
                inventory_item_id,
                item_number,
                description_raw,
                category_name,
                item_status,
                primary_uom_val,
                tipo,
                origen,
                organization_code,
                business_unit_name,
                almacenaje,
                (embedding <=> %s::vector) AS distancia
            FROM inv_embeddings
            WHERE request_id = %s
        """
        params: list = [emb_str, request_id]

        if categoria_origen:
            # Aprovecha idx_emb_request_cat_org para acotar ANTES del HNSW
            query += " AND category_name = %s"
            params.append(categoria_origen)

        # FETCH FIRST es compatible con pgvector ORDER BY distancia ASC + HNSW
        query += """
            ORDER BY distancia ASC
            FETCH FIRST %s ROWS ONLY
        """
        params.append(top_k)

        cur.execute(query, params)
        filas = cur.fetchall()
        cur.close()

        # ── 3. Post-proceso: boosts + umbral ─────────────────────────────────────────
        candidatos: list[dict] = []

        for fila in filas:
            (inv_id, item_num, desc_raw, cat_name, status,
             cand_uom, cand_tipo, cand_origen, org_code, bu_name, alm) = fila[0:11]
            distancia    = float(fila[11])
            cosine_score = round(1.0 - distancia, 4)  # <=> retorna distancia, no similitud

            scores = self._calcular_score(
                cosine_score,
                cand_uom, cand_tipo, cand_origen,
                uom_origen, tipo_origen, origen_origen,
            )

            # Aplicar umbral del DDL: "≥ 0.85 para entrar al grupo"
            if scores["final_score"] < umbral:
                continue

            candidatos.append({
                "inventory_item_id": inv_id,
                "item_number":       item_num,
                "item_description":  desc_raw,
                "category_name":     cat_name,
                "item_status":       status,
                "organization_code": org_code,
                "business_unit_name": bu_name,
                "primary_uom_val":   cand_uom,
                "almacenaje":        alm,
                "origen":            cand_origen,
                "tipo":              cand_tipo,
                **scores,
            })

        print(f"[RAG] {len(candidatos)} candidatos superaron el umbral {umbral} de {len(filas)} recuperados.\n")
        return candidatos

    # ─────────────────────────────────────────────────────────────────────────
    # PERSISTENCIA DE GRUPOS EN inv_similarity_results
    # ─────────────────────────────────────────────────────────────────────────
    def persistir_grupo(
        self,
        request_id: str,
        group_id: int,
        group_label: str,
        anchor: dict,
        candidatos: list[dict],
        group_risk: str = "medium",
    ) -> None:
        """
        Persiste un grupo completo en inv_similarity_results.

        Estructura del grupo (DDL):
            is_anchor=TRUE  → ítem Base (sin score bar en UI, sin cosine_score)
            is_anchor=FALSE → candidatos ordenados por final_score DESC

        Cálculos alineados al DDL:
            group_size     = len(candidatos) + 1 (anchor incluido)
            group_avg_score = promedio de final_score de TODOS los candidatos
                              (no del anchor, que no tiene score)
            group_risk     = calificación del grupo (high/medium/low)

        ON CONFLICT DO UPDATE:
            A diferencia de la inserción de embeddings, los resultados de similitud
            SÍ deben actualizarse si cambia el umbral o los boosts (DDL: "Se puede
            cambiar el umbral de similitud sin re-vectorizar: solo relanzar el VECTOR_SEARCH").
        """
        if not candidatos:
            return

        group_size      = len(candidatos) + 1  # anchor + candidatos
        group_avg_score = round(mean(c["final_score"] for c in candidatos), 4)
        group_category  = anchor.get("category_name", "")

        cur = self.conn.cursor()

        # ── Insertar el ANCHOR (is_anchor=TRUE, sin scores) ──────────────────────────
        cur.execute("""
            INSERT INTO inv_similarity_results (
                request_id,         group_id,           group_label,
                group_category,     group_risk,         group_size,         group_avg_score,
                inventory_item_id,  item_number,        item_description,   category_name,
                is_anchor,          cosine_score,       uom_boost,          tipo_boost,
                origen_boost,       final_score,        item_status,
                organization_code,  business_unit_name, primary_uom_val,
                almacenaje,         origen,             tipo
            )
            VALUES (
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                TRUE, NULL, NULL, NULL,
                NULL, NULL, %s,
                %s, %s, %s,
                %s, %s, %s
            )
            ON CONFLICT (request_id, inventory_item_id) DO UPDATE SET
                group_id        = EXCLUDED.group_id,
                group_label     = EXCLUDED.group_label,
                group_category  = EXCLUDED.group_category,
                group_risk      = EXCLUDED.group_risk,
                group_size      = EXCLUDED.group_size,
                group_avg_score = EXCLUDED.group_avg_score,
                is_anchor       = TRUE,
                cosine_score    = NULL,
                final_score     = NULL
        """, [
            request_id,                     group_id,                   group_label,
            group_category,                 group_risk,                 group_size,         group_avg_score,
            anchor["inventory_item_id"],    anchor["item_number"],      anchor["item_description"],  anchor.get("category_name"),
            anchor.get("item_status"),
            anchor.get("organization_code"), anchor.get("business_unit_name"), anchor.get("primary_uom_val"),
            anchor.get("almacenaje"),        anchor.get("origen"),             anchor.get("tipo"),
        ])

        # ── Insertar CANDIDATOS (is_anchor=FALSE, con todos los scores) ──────────────
        for candidato in candidatos:
            cur.execute("""
                INSERT INTO inv_similarity_results (
                    request_id,         group_id,           group_label,
                    group_category,     group_risk,         group_size,         group_avg_score,
                    inventory_item_id,  item_number,        item_description,   category_name,
                    is_anchor,          cosine_score,       uom_boost,          tipo_boost,
                    origen_boost,       final_score,        item_status,
                    organization_code,  business_unit_name, primary_uom_val,
                    almacenaje,         origen,             tipo
                )
                VALUES (
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    FALSE, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s
                )
                ON CONFLICT (request_id, inventory_item_id) DO UPDATE SET
                    group_id        = EXCLUDED.group_id,
                    group_label     = EXCLUDED.group_label,
                    group_category  = EXCLUDED.group_category,
                    group_risk      = EXCLUDED.group_risk,
                    group_size      = EXCLUDED.group_size,
                    group_avg_score = EXCLUDED.group_avg_score,
                    cosine_score    = EXCLUDED.cosine_score,
                    uom_boost       = EXCLUDED.uom_boost,
                    tipo_boost      = EXCLUDED.tipo_boost,
                    origen_boost    = EXCLUDED.origen_boost,
                    final_score     = EXCLUDED.final_score
            """, [
                request_id,                         group_id,                       group_label,
                group_category,                     group_risk,                     group_size,                 group_avg_score,
                candidato["inventory_item_id"],     candidato["item_number"],       candidato["item_description"], candidato.get("category_name"),
                candidato["cosine_score"],          candidato["uom_boost"],         candidato["tipo_boost"],
                candidato["origen_boost"],          candidato["final_score"],       candidato.get("item_status"),
                candidato.get("organization_code"), candidato.get("business_unit_name"), candidato.get("primary_uom_val"),
                candidato.get("almacenaje"),        candidato.get("origen"),        candidato.get("tipo"),
            ])

        self.conn.commit()
        cur.close()
        print(f"[DB] Grupo #{group_id} '{group_label}' persistido: 1 anchor + {len(candidatos)} candidatos.\n")

    # ─────────────────────────────────────────────────────────────────────────
    # HELPER: BÚSQUEDA + PERSISTENCIA EN UN SOLO PASO
    # ─────────────────────────────────────────────────────────────────────────
    def buscar_y_persistir(
        self,
        anchor: dict,
        request_id: str,
        group_id: int,
        group_label: str,
        group_risk: str = "medium",
        top_k: int = 10,
        umbral: float = UMBRAL_SIMILITUD,
    ) -> list[dict]:
        """
        Wrapper que ejecuta buscar() y luego persistir_grupo() en secuencia.

        El anchor es un dict con los metadatos del ítem maestro del grupo.
        Campos esperados del anchor (mismos keys que el metadata del chunk):
            ITEM_DESCRIPTION, CATEGORY_NAME, PRIMARY_UOM_VAL,
            TIPO, ORIGEN, ALMACENAJE, INVENTORY_ITEM_ID,
            ITEM_NUMBER, ITEM_STATUS, ORGANIZATION_CODE, BUSINESS_UNIT_NAME

        Retorna los candidatos encontrados (útil para componer la respuesta del agente).
        """
        candidatos = self.buscar(
            producto_texto    = anchor.get("ITEM_DESCRIPTION", ""),
            request_id        = request_id,
            categoria_origen  = anchor.get("CATEGORY_NAME"),
            uom_origen        = anchor.get("PRIMARY_UOM_VAL"),
            tipo_origen       = anchor.get("TIPO"),
            origen_origen     = anchor.get("ORIGEN"),
            almacenaje_origen = anchor.get("ALMACENAJE"),
            top_k             = top_k,
            umbral            = umbral,
        )

        # Excluir el anchor de su propia lista de candidatos
        anchor_id   = anchor.get("INVENTORY_ITEM_ID")
        candidatos  = [c for c in candidatos if c["inventory_item_id"] != anchor_id]

        # Normalizar el dict del anchor al mismo esquema que los candidatos
        anchor_normalizado = {
            "inventory_item_id": anchor_id,
            "item_number":       anchor.get("ITEM_NUMBER"),
            "item_description":  anchor.get("ITEM_DESCRIPTION"),
            "category_name":     anchor.get("CATEGORY_NAME"),
            "item_status":       anchor.get("ITEM_STATUS"),
            "organization_code": anchor.get("ORGANIZATION_CODE"),
            "business_unit_name": anchor.get("BUSINESS_UNIT_NAME"),
            "primary_uom_val":   anchor.get("PRIMARY_UOM_VAL"),
            "almacenaje":        anchor.get("ALMACENAJE"),
            "origen":            anchor.get("ORIGEN"),
            "tipo":              anchor.get("TIPO"),
        }

        if candidatos:
            self.persistir_grupo(
                request_id   = request_id,
                group_id     = group_id,
                group_label  = group_label,
                anchor       = anchor_normalizado,
                candidatos   = candidatos,
                group_risk   = group_risk,
            )

        return candidatos

    # ─────────────────────────────────────────────────────────────────────────
    # DISPLAY
    # ─────────────────────────────────────────────────────────────────────────
    def mostrar_resultado(
        self,
        anchor: dict,
        request_id: str,
        top_k: int = 5,
        umbral: float = UMBRAL_SIMILITUD,
    ) -> None:
        """
        Imprime en consola el resultado de la búsqueda para inspección/debug.
        Muestra el formato de la tabla pRes() del prototipo.
        """
        desc = anchor.get("ITEM_DESCRIPTION", "")
        print(f"\n{'=' * 60}\n[Anchor] {desc}\n{'=' * 60}\n")

        candidatos = self.buscar(
            producto_texto    = desc,
            request_id        = request_id,
            categoria_origen  = anchor.get("CATEGORY_NAME"),
            uom_origen        = anchor.get("PRIMARY_UOM_VAL"),
            tipo_origen       = anchor.get("TIPO"),
            origen_origen     = anchor.get("ORIGEN"),
            almacenaje_origen = anchor.get("ALMACENAJE"),
            top_k             = top_k,
            umbral            = umbral,
        )

        anchor_id = anchor.get("INVENTORY_ITEM_ID")
        candidatos = [c for c in candidatos if c["inventory_item_id"] != anchor_id]

        if not candidatos:
            print("  → No se encontraron candidatos similares por encima del umbral.\n")
            return

        for i, r in enumerate(candidatos, 1):
            print(
                f"\n  [#{i}] Final Score : {r['final_score']}  "
                f"(Cosine: {r['cosine_score']} × {COSINE_WEIGHT} + "
                f"UOM: {r['uom_boost']} + Tipo: {r['tipo_boost']} + Origen: {r['origen_boost']})"
            )
            print(f"        Item Number : {r['item_number']}")
            print(f"        Descripción : {r['item_description']}")
            print(f"        Categoría   : {r['category_name']}")
            print(f"        UOM / Tipo / Origen : {r['primary_uom_val']} / {r['tipo']} / {r['origen']}")
            print(f"        Estado      : {r['item_status']}")
        print()

    # ─────────────────────────────────────────────────────────────────────────
    # LIMPIEZA
    # ─────────────────────────────────────────────────────────────────────────
    def cerrar(self) -> None:
        if self.conn:
            self.conn.close()
            print(f"\n{'=' * 60}\n[DB] Conexión cerrada.\n{'=' * 60}\n")