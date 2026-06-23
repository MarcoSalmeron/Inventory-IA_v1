-- ============================================================
-- INVENTORY IA — DDL PostgreSQL + pgvector
-- Schema: inventory_ia
-- Modelo de embeddings: paraphrase-multilingual-MiniLM-L12-v2
-- Dimensiones: VECTOR(384)
-- ============================================================
-- Orden de creación (respeta dependencias FK):
--   1. inv_analysis_runs   ← registro de cada ejecución del pipeline
--   2. inv_items_raw       ← copia fiel del CSV del job Oracle
--   3. inv_embeddings      ← vectores normalizados por ítem
--   4. inv_similarity_results ← grupos detectados + workflow aprobación
-- ============================================================

CREATE SCHEMA IF NOT EXISTS inventory_ia;
CREATE EXTENSION IF NOT EXISTS vector;       -- pgvector
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; -- por si se usa uuid en el futuro


-- ============================================================
-- TABLA 1: inv_analysis_runs
--
-- MOTIVO: Es el registro de estado del pipeline completo.
--
-- El pipeline tiene 5 fases encadenadas:
--   [extract] → [embed] → [similarity] → [crossref] → [propose]
--
-- Cada fase puede fallar de forma independiente. Sin esta tabla,
-- cualquier fallo obliga a reiniciar desde el job Oracle — que
-- puede tardar minutos y consume recursos del ERP del cliente.
--
-- Con esta tabla FastAPI puede:
--   1. Reanudar desde la fase exacta donde falló
--   2. Mostrar progreso al frontend (status + current_phase)
--   3. Auditar cuánto tardó cada fase y cuántos ítems procesó
--   4. Evitar correr dos análisis paralelos para la misma org
--
-- Relación con las demás tablas:
--   inv_items_raw.request_id           → FK a esta tabla
--   inv_embeddings.request_id          → FK a esta tabla
--   inv_similarity_results.request_id  → FK a esta tabla
-- ============================================================
CREATE TABLE IF NOT EXISTS inv_analysis_runs (

    -- Identificador único del análisis
    -- Generado por FastAPI con formato INV-{timestamp_b36}-{random}
    -- Ejemplo: INV-M9XK2P-4FR1
    -- Es el mismo request_id que viaja por todas las tablas
    request_id              VARCHAR(50)     PRIMARY KEY,

    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ,

    -- ── Parámetros de la ejecución ───────────────────────────
    organization_id         VARCHAR(50),        -- P_INV_ORGANIZATION_ID del CSV
    organization_code       VARCHAR(50),        -- ORGANIZATION_CODE  e.g. "200"
    business_unit_id        VARCHAR(50),        -- BUSINESS_UNIT_ID
    business_unit_name      VARCHAR(200),       -- BUSINESS_UNIT_NAME e.g. "542_URY_SBU"

    -- ── Estado del pipeline ──────────────────────────────────
    -- Flujo normal:
    --   PENDING → EXTRACTING → EXTRACTED → EMBEDDING → EMBEDDED
    --           → ANALYZING → ANALYZED → AWAITING_APPROVAL → DONE
    -- Flujo de error:
    --   cualquier estado → ERROR (ver error_phase + error_message)
    --
    -- FastAPI usa este campo para decidir desde qué fase reanudar:
    --   PENDING / ERROR en extract → volver a invocar job Oracle
    --   EXTRACTED                 → saltar a embed (CSV ya en raw)
    --   EMBEDDED                  → saltar a similarity (vectors ya listos)
    --   ANALYZED                  → saltar a crossref/propose
    status                  VARCHAR(30)     NOT NULL DEFAULT 'PENDING'
                            CHECK (status IN (
                                'PENDING',
                                'EXTRACTING',       -- job Oracle en curso
                                'EXTRACTED',        -- CSV en inv_items_raw
                                'EMBEDDING',        -- vectorizando ítems
                                'EMBEDDED',         -- todos vectorizados
                                'ANALYZING',        -- VECTOR_SEARCH en curso
                                'ANALYZED',         -- grupos detectados
                                'AWAITING_APPROVAL',-- esperando al usuario
                                'DONE',             -- ERP actualizado
                                'ERROR'
                            )),

    -- Fase activa del grafo LangGraph
    -- Mapea 1:1 con los nodos del StateGraph en agents/inventory_graph.py
    current_phase           VARCHAR(20)
                            CHECK (current_phase IN (
                                'extract',      -- OracleFusionLoader
                                'embed',        -- SentenceTransformer.encode()
                                'similarity',   -- VECTOR_SEARCH pgvector
                                'crossref',     -- OTBI por grupo
                                'propose'       -- LLM → acción sugerida
                            )),

    -- ── Métricas del job Oracle (fase extract) ───────────────
    job_id_oracle           VARCHAR(100),       -- ID del job ESS-JOB-XXXXXXXXX
    job_status_oracle       VARCHAR(20),        -- RUNNING / SUCCEEDED / FAILED
    job_submitted_at        TIMESTAMPTZ,        -- cuándo se invocó el job
    job_completed_at        TIMESTAMPTZ,        -- cuándo terminó (polling)

    -- ── Métricas del pipeline ────────────────────────────────
    -- Alimentan los 4 KPI cards del prototipo pRes():
    --   "Ítems analizados" | "Grupos detectados" | "Ítems involucrados" | "Score promedio"
    items_total             INTEGER,            -- total ítems en el CSV
    items_valid             INTEGER,            -- ítems con descripción válida
    items_embedded          INTEGER,            -- ítems vectorizados exitosamente
    groups_detected         INTEGER,            -- grupos de similitud (KPI prototipo)
    items_involucrados      INTEGER,            -- ítems dentro de grupos (KPI prototipo)
    avg_score               NUMERIC(5,4),       -- score promedio (KPI prototipo)
    pairs_compared          INTEGER,            -- total pares evaluados por VECTOR_SEARCH

    -- ── Control de errores ───────────────────────────────────
    error_phase             VARCHAR(20),        -- en qué fase del grafo falló
    error_message           TEXT,               -- stacktrace o mensaje de error
    retry_count             SMALLINT            NOT NULL DEFAULT 0

);

CREATE INDEX IF NOT EXISTS idx_runs_status
    ON inventory_ia.inv_analysis_runs (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_runs_org
    ON inventory_ia.inv_analysis_runs (organization_code, created_at DESC);

COMMENT ON TABLE inventory_ia.inv_analysis_runs IS
    'Registro de estado de cada ejecución del pipeline LangGraph. '
    'Permite reanudar desde cualquier fase sin reinvocar el job Oracle. '
    'Los campos items_total, groups_detected, items_involucrados y avg_score '
    'alimentan directamente los 4 KPI cards del prototipo pRes().';


-- ============================================================
-- TABLA 2: inv_items_raw
--
-- MOTIVO: Copia fiel e inmutable del CSV generado por el job Oracle.
--
-- El pipeline necesita esta tabla por dos razones:
--
--   A) RESILIENCIA: si el servidor cae durante el embedding,
--      el CSV ya está guardado. FastAPI puede reanudar desde
--      la fase 'embed' sin volver a invocar el job Oracle.
--
--   B) REPROCESAMIENTO: si se cambia el modelo de embeddings
--      (MiniLM → mpnet) o los campos del composite_text,
--      se pueden regenerar los vectores leyendo esta tabla
--      sin tocar el ERP.
--
-- Los 46 campos reflejan exactamente las columnas del CSV Oracle.
-- Los typos de Oracle se preservan tal cual:
--   LEGAL_ENTTITY_ID  (doble T)
--   UNIT_WEIGTH_QUANTITY (falta la H)
-- Si se "corrigen", el parser del CSV fallará al mapear columnas.
-- ============================================================
CREATE TABLE IF NOT EXISTS inv_items_raw (

    id                          BIGSERIAL       PRIMARY KEY,

    -- FK al análisis — permite borrar todos los raw de un análisis
    request_id                  VARCHAR(50)     NOT NULL
                                REFERENCES inventory_ia.inv_analysis_runs(request_id)
                                ON DELETE CASCADE,

    ingested_at                 TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    job_id                      VARCHAR(100),       -- ID del job Oracle que generó el CSV
    source_file                 VARCHAR(255),       -- nombre del archivo descargado

    -- ── Identifiers Oracle Fusion ────────────────────────────
    p_inv_organization_id       VARCHAR(50),
    inventory_item_id           VARCHAR(50)     NOT NULL,
    organization_id             VARCHAR(50),
    organization_code           VARCHAR(50),
    business_unit_id            VARCHAR(50),
    business_unit_name          VARCHAR(200),
    legal_entity_id             VARCHAR(50),        -- columna: LEGAL_ENTTITY_ID (typo Oracle)
    master_org_id               VARCHAR(50),
    item_class                  VARCHAR(50),

    -- ── Datos del ítem ───────────────────────────────────────
    item_number                 VARCHAR(100)    NOT NULL,
    item_description            TEXT,
    long_description            TEXT,
    category_name               VARCHAR(200),
    item_status                 VARCHAR(50),        -- ACTIVO / TRAN-STOCK / INACTIVO
    item_status_name            VARCHAR(100),
    item_status_description     TEXT,
    approval_status             VARCHAR(10),        -- A = Approved

    -- ── Unidades y medidas ───────────────────────────────────
    primary_uom_val             VARCHAR(20),        -- CJA / UNI / KG
    secondary_uom               VARCHAR(20),
    dimension_uom               VARCHAR(20),
    weight_uom                  VARCHAR(20),
    volume_uom                  VARCHAR(20),
    unit_width_quantity         NUMERIC(18,6),
    unit_length_quantity        NUMERIC(18,6),
    unit_height_quantity        NUMERIC(18,6),
    unit_weight_quantity        NUMERIC(18,6),      -- columna: UNIT_WEIGTH_QUANTITY (typo Oracle)
    unit_volume_quantity        NUMERIC(18,6),
    primary_transaction_qty     NUMERIC(18,6),

    -- ── Flags de comportamiento (Y/N del CSV) ────────────────
    inventory_item_flag         CHAR(1),
    stock_enabled_flag          CHAR(1),
    customer_order_flag         CHAR(1),
    customer_order_enabled_flag CHAR(1),
    shippable_flag              CHAR(1),
    invoiced_flag               CHAR(1),
    purchasing_item_flag        CHAR(1),
    purchasing_enabled_flag     CHAR(1),
    purchasing_tax_code         VARCHAR(50),

    -- ── Campos custom del cliente ────────────────────────────
    -- No vienen en todos los CSVs Oracle — pueden ser NULL
    almacenaje                  VARCHAR(50),        -- SECO / FRIO / CONGELADO
    origen                      VARCHAR(50),        -- NACIONAL / IMPORTADO
    tipo                        VARCHAR(50),        -- PRODUCTIVO / NO PRODUCTIVO
    proveedor                   VARCHAR(255),

    -- ── Auditoría Oracle ─────────────────────────────────────
    version_id                  VARCHAR(20),
    creation_date               TIMESTAMPTZ,
    last_update_date            TIMESTAMPTZ,
    created_by                  VARCHAR(200),
    last_updated_by             VARCHAR(200),

    CONSTRAINT uq_raw_request_item_org
        UNIQUE (request_id, inventory_item_id, organization_code)
);

CREATE INDEX IF NOT EXISTS idx_raw_request_id
    ON inv_items_raw (request_id);

CREATE INDEX IF NOT EXISTS idx_raw_org_cat
    ON inv_items_raw (organization_code, category_name);

CREATE INDEX IF NOT EXISTS idx_raw_item_number
    ON inv_items_raw (item_number);

CREATE INDEX IF NOT EXISTS idx_raw_status
    ON inv_items_raw (item_status);

COMMENT ON TABLE inv_items_raw IS
    'Copia fiel del CSV del job Oracle. 46 columnas exactas del reporte. '
    'Inmutable: nunca se modifica después de la inserción. '
    'Permite regenerar embeddings con otro modelo sin reinvocar el job Oracle. '
    'Typos de Oracle preservados: LEGAL_ENTTITY_ID, UNIT_WEIGTH_QUANTITY.';


-- ============================================================
-- TABLA 3: inv_embeddings
--
-- MOTIVO: Separa el paso costoso de vectorización del análisis.
--
-- Generar un embedding requiere cargar el modelo en memoria
-- (~420MB para MiniLM-L12) y hacer inferencia por cada ítem.
-- Para 4,000 ítems en CPU tarda ~40 segundos.
--
-- Si se separa en su propia tabla:
--   - Se puede cambiar el umbral de similitud (0.85 → 0.80)
--     sin re-vectorizar: solo relanzar el VECTOR_SEARCH
--   - Se puede cambiar el composite_text (agregar ALMACENAJE)
--     sin reinvocar el job Oracle: re-vectorizar desde raw
--   - Se pueden comparar ítems de diferentes request_ids
--     si se necesita análisis histórico entre análisis
--
-- Solo se insertan ítems válidos:
--   - item_description NOT NULL y longitud > 3 chars
--   - item_status != 'INACTIVO' (opcional según regla de negocio)
--
-- El composite_text es el texto que realmente se vectoriza:
--   normalize(item_description) + category_name_clean + almacenaje
-- Se guarda para auditoría — permite reproducir el vector exacto.
-- ============================================================
CREATE TABLE IF NOT EXISTS inv_embeddings (

    id                      BIGSERIAL       PRIMARY KEY,

    request_id              VARCHAR(50)     NOT NULL
                            REFERENCES inv_analysis_runs(request_id)
                            ON DELETE CASCADE,

    embedded_at             TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Qué modelo generó este vector
    -- Crítico para saber si los vectores son comparables entre sí
    -- No mezclar vectores de MiniLM con vectores de mpnet
    embedding_model         VARCHAR(100)    NOT NULL,   -- "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dimensions    SMALLINT        NOT NULL DEFAULT 384,

    -- ── Referencia al ítem (desnormalizado) ──────────────────
    -- Se duplican aquí para evitar JOINs durante el VECTOR_SEARCH.
    -- El VECTOR_SEARCH ya es costoso — agregar un JOIN lo hace más lento.
    inventory_item_id       VARCHAR(50)     NOT NULL,
    organization_code       VARCHAR(50)     NOT NULL,
    business_unit_name      VARCHAR(200),
    category_name           VARCHAR(200),   -- clave de partición: filtrar ANTES del VECTOR_SEARCH
    item_number             VARCHAR(100),
    item_status             VARCHAR(50),

    -- Campos para boost post-cosine (guardados aquí para no hacer JOIN)
    primary_uom_val         VARCHAR(20),    -- boost +0.15 si mismo UOM
    almacenaje              VARCHAR(50),
    origen                  VARCHAR(50),    -- boost +0.05 si mismo ORIGEN
    tipo                    VARCHAR(50),    -- boost +0.10 si mismo TIPO

    -- ── Textos de la normalización ───────────────────────────
    -- Guardar los 3 textos permite auditar exactamente
    -- qué vio el modelo y reproducir el vector si es necesario
    description_raw         TEXT,           -- descripción original del CSV
    description_normalized  TEXT,           -- limpia: sin prefijos ALI./LIM./EMB., cantidades, stop words
    composite_text          TEXT,           -- texto final enviado al modelo: norm + category + almacenaje

    -- ── El vector ────────────────────────────────────────────
    -- VECTOR(384) para MiniLM-L12-v2
    -- Cambiar a VECTOR(768) si se migra a mpnet-base-v2
    -- normalize_embeddings=True en SentenceTransformer → cosine = producto punto
    embedding               VECTOR(768)     NOT NULL,

    CONSTRAINT uq_emb_request_item
        UNIQUE (request_id, inventory_item_id)
);

-- Índice HNSW — búsqueda aproximada de vecinos más cercanos
-- vector_cosine_ops: operador <=> (distancia coseno)
-- m=16: número de conexiones por nodo (más = más preciso, más memoria)
-- ef_construction=64: tamaño del grafo durante construcción (más = más preciso, más lento al insertar)
-- Para producción con >10k ítems considerar m=32, ef_construction=128
CREATE INDEX IF NOT EXISTS idx_emb_hnsw_cosine
    ON inv_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Índice compuesto para el filtro previo al VECTOR_SEARCH
-- Siempre filtrar por request_id + category_name ANTES del VECTOR_SEARCH
-- Reduce N² → suma(ni²): 10k ítems en 20 cats de 500 = 20x menos comparaciones
CREATE INDEX IF NOT EXISTS idx_emb_request_cat_org
    ON inv_embeddings (request_id, organization_code, category_name);

CREATE INDEX IF NOT EXISTS idx_emb_item
    ON inv_embeddings (inventory_item_id);

COMMENT ON TABLE inv_embeddings IS
    'Vectores VECTOR(384) por ítem generados con MiniLM-L12-v2. '
    'Solo ítems válidos (descripción no vacía). '
    'Separado de inv_items_raw para poder recalcular similitud con diferente '
    'umbral sin re-vectorizar, y re-vectorizar con otro modelo sin volver al ERP. '
    'Filtrar SIEMPRE por category_name antes de usar el índice HNSW.';

COMMENT ON COLUMN inv_embeddings.embedding IS
    'Vector de 384 dimensiones generado con paraphrase-multilingual-MiniLM-L12-v2. '
    'Normalizado (L2=1) → operador <=> equivale a distancia coseno. '
    'Migrar a VECTOR(768) si se cambia a paraphrase-multilingual-mpnet-base-v2.';

COMMENT ON COLUMN inv_embeddings.composite_text IS
    'Texto exacto enviado al modelo. Composición: '
    'normalize(item_description) + category_name_sin_COSTO + almacenaje. '
    'Guardar este campo permite reproducir el vector exacto para auditoría.';


-- ============================================================
-- TABLA 4: inv_similarity_results
--
-- MOTIVO: Persistir los grupos detectados y el workflow de aprobación.
--
-- Esta tabla tiene DOS responsabilidades que justifican su existencia:
--
--   A) RESULTADOS DEL ANÁLISIS (pantalla pRes() del prototipo):
--      Guarda los grupos con sus ítems, scores y riesgo.
--      El frontend consulta esta tabla para renderizar la tabla
--      "Artículos con descripción similar".
--
--   B) WORKFLOW DE APROBACIÓN (pantallas pRef() y pApr() del prototipo):
--      Guarda la decisión del usuario por cada ítem:
--      proposed_action (LLM) → approved_action (usuario) → erp_updated
--      Sin esta tabla no hay estado compartido entre el agente
--      y el usuario — no se puede saber qué aprobó ni qué enviar al ERP.
--
-- Estructura de una fila:
--   Una fila por ÍTEM dentro de su grupo.
--   is_anchor=TRUE  → ítem maestro (badge "Base" en UI, sin score bar)
--   is_anchor=FALSE → candidato (score bar + número en UI)
--
-- Columnas que corresponden exactamente al prototipo pRes():
--   group_id + group_label  → columna "Grupo"
--   item_number             → columna "Item number"
--   item_description        → columna "Descripción"
--   category_name           → columna "Categoría"
--   is_anchor + final_score → columna "Similitud"
--   item_status             → columna "Estado"
--   group_risk + item_risk  → columna "Riesgo"
-- ============================================================

-- Separador --
CREATE TABLE IF NOT EXISTS inv_similarity_results (

    id                      BIGSERIAL       PRIMARY KEY,

    request_id              VARCHAR(50)     NOT NULL
                            REFERENCES inv_analysis_runs(request_id)
                            ON DELETE CASCADE,

    analyzed_at             TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- ── Columna "Grupo" del prototipo ────────────────────────
    -- Mostrado como encabezado de sección: "#1 — Placa Starbucks"
    -- Solo visible en la primera fila del grupo (is_anchor=TRUE)
    group_id                INTEGER         NOT NULL,
    group_label             VARCHAR(255)    NOT NULL,   -- generado por propose_node (LLM)
    group_category          VARCHAR(200)    NOT NULL,   -- CATEGORY_NAME del grupo
    group_risk              VARCHAR(10)     NOT NULL    -- badge en primera fila del grupo
                            CHECK (group_risk IN ('high','medium','low')),
    group_size              SMALLINT        NOT NULL,
    group_avg_score         NUMERIC(5,4),

    -- ── Columna "Item number" del prototipo ──────────────────
    inventory_item_id       VARCHAR(50)     NOT NULL,
    item_number             VARCHAR(100)    NOT NULL,

    -- ── Columna "Descripción" del prototipo ──────────────────
    item_description        TEXT            NOT NULL,

    -- ── Columna "Categoría" del prototipo ────────────────────
    -- Badge gris, visible solo en is_anchor=TRUE
    category_name           VARCHAR(200),

    -- ── Columna "Similitud" del prototipo ────────────────────
    -- is_anchor=TRUE  → badge "Base" (sin barra, sin número)
    -- is_anchor=FALSE → score bar coloreada + número e.g. "0.91"
    is_anchor               BOOLEAN         NOT NULL DEFAULT FALSE,
    cosine_score            NUMERIC(5,4),               -- NULL si is_anchor
    uom_boost               NUMERIC(4,3),               -- +0.150 si mismo UOM
    tipo_boost              NUMERIC(4,3),               -- +0.100 si mismo TIPO
    origen_boost            NUMERIC(4,3),               -- +0.050 si mismo ORIGEN
    final_score             NUMERIC(5,4),               -- NULL si is_anchor; ≥ 0.85 para entrar

    -- ── Columna "Estado" del prototipo ───────────────────────
    -- badge: verde=ACTIVO / amarillo=TRAN-STOCK / rojo=INACTIVO
    item_status             VARCHAR(50)     NOT NULL,
    item_status_name        VARCHAR(100),

    -- ── Columna "Riesgo" del prototipo ───────────────────────
    -- Badge, visible solo en is_anchor=TRUE (misma lógica que group_risk)
    item_risk               VARCHAR(10)
                            CHECK (item_risk IN ('high','medium','low')),

    -- ── Campos para pantalla Cross-ref ───────────────────────
    organization_code       VARCHAR(50),
    business_unit_name      VARCHAR(200),
    primary_uom_val         VARCHAR(20),
    almacenaje              VARCHAR(50),
    origen                  VARCHAR(50),
    tipo                    VARCHAR(50),
    proveedor               VARCHAR(255),

    -- ── Workflow de aprobación ───────────────────────────────
    -- proposed_action: sugerencia del LLM (propose_node)
    -- approved_action: decisión final del usuario en pApr()
    -- erp_updated: TRUE cuando el job Oracle ejecutó el cambio
    proposed_action         VARCHAR(20)
                            CHECK (proposed_action IN ('keep','merge','obsolete','review')),
    approved_action         VARCHAR(20)
                            CHECK (approved_action IN ('keep','merge','obsolete','review')),
    approved_by             VARCHAR(200),
    approved_at             TIMESTAMPTZ,
    erp_updated             BOOLEAN         NOT NULL DEFAULT FALSE,
    erp_updated_at          TIMESTAMPTZ,
    erp_job_id              VARCHAR(100),

    CONSTRAINT uq_result_request_item
        UNIQUE (request_id, inventory_item_id)
);

-- Índice principal: orden exacto que usa la vista v_results_by_group
-- group_id ASC → grupos en orden
-- is_anchor DESC → ítem Base siempre primero dentro del grupo
-- final_score DESC → candidatos ordenados por similitud
CREATE INDEX IF NOT EXISTS idx_sim_request_group_order
    ON inv_similarity_results
    (request_id, group_id ASC, is_anchor DESC, final_score DESC NULLS LAST);

-- Índice parcial: solo filas pendientes de enviar al ERP
-- Evita full scan al buscar aprobaciones pendientes
CREATE INDEX IF NOT EXISTS idx_sim_pending_erp
    ON inv_similarity_results (request_id, approved_action)
    WHERE erp_updated = FALSE AND approved_action IS NOT NULL;

COMMENT ON TABLE inv_similarity_results IS
    'Una fila por ítem dentro de su grupo de similitud. '
    'Doble responsabilidad: '
    '(A) Resultado del análisis — alimenta la tabla del prototipo pRes() '
    'con columnas Grupo | Item number | Descripción | Categoría | Similitud | Estado | Riesgo. '
    '(B) Workflow de aprobación — guarda proposed_action (LLM) → approved_action (usuario) '
    '→ erp_updated (job Oracle). Sin esta tabla no hay estado compartido entre agente y usuario.';

COMMENT ON COLUMN inv_similarity_results.is_anchor IS
    'TRUE = ítem maestro del grupo → badge "Base" en UI sin score bar. '
    'FALSE = candidato → score bar coloreada + valor numérico. '
    'El anchor es el ítem con mayor stock activo y más referencias en módulos Oracle.';

COMMENT ON COLUMN inv_similarity_results.final_score IS
    'Score ponderado: cosine×0.70 + uom_boost + tipo_boost + origen_boost. '
    'Umbral mínimo para entrar al grupo: ≥ 0.85. '
    'NULL cuando is_anchor=TRUE (el anchor no se compara contra sí mismo).';


-- ============================================================
-- VISTAS
-- ============================================================

-- v_results_by_group
-- Alimenta la tabla del prototipo pRes() con el orden correcto:
-- is_anchor DESC garantiza que el ítem Base aparezca primero en cada grupo
CREATE OR REPLACE VIEW v_results_by_group AS
SELECT
    r.request_id,
    r.group_id,
    r.group_label,
    r.group_category,
    r.group_risk,
    r.group_size,
    r.group_avg_score,
    r.inventory_item_id,
    r.item_number,
    r.item_description,
    r.category_name,
    r.is_anchor,
    r.final_score,
    r.cosine_score,
    r.item_status,
    r.item_status_name,
    r.item_risk,
    r.organization_code,
    r.primary_uom_val,
    r.almacenaje,
    r.origen,
    r.tipo,
    r.proveedor,
    r.proposed_action,
    r.approved_action,
    r.erp_updated
FROM inv_similarity_results r
ORDER BY
    r.request_id,
    r.group_id       ASC,
    r.is_anchor      DESC,
    r.final_score    DESC NULLS LAST;

-- v_kpi_summary
-- Alimenta los 4 KPI cards del prototipo pRes()
CREATE OR REPLACE VIEW v_kpi_summary AS
SELECT
    a.request_id,
    a.organization_code,
    a.business_unit_name,
    a.items_total                                       AS items_analizados,
    a.groups_detected                                   AS grupos_detectados,
    COUNT(DISTINCT r.inventory_item_id)                 AS items_involucrados,
    ROUND(AVG(CASE WHEN NOT r.is_anchor
              THEN r.final_score END)::NUMERIC, 3)      AS score_promedio,
    a.status,
    a.created_at,
    a.updated_at
FROM inv_analysis_runs a
LEFT JOIN inv_similarity_results r
       ON r.request_id = a.request_id
GROUP BY
    a.request_id, a.organization_code, a.business_unit_name,
    a.items_total, a.groups_detected, a.status,
    a.created_at, a.updated_at;

-- fn_get_analysis_results(p_request_id)
-- Una sola query para FastAPI: KPIs + filas de tabla sin dos roundtrips
CREATE OR REPLACE FUNCTION fn_get_analysis_results(
    p_request_id VARCHAR
)
RETURNS TABLE (
    items_analizados    INTEGER,
    grupos_detectados   INTEGER,
    items_involucrados  BIGINT,
    score_promedio      NUMERIC,
    group_id            INTEGER,
    group_label         VARCHAR,
    group_category      VARCHAR,
    group_risk          VARCHAR,
    group_size          SMALLINT,
    inventory_item_id   VARCHAR,
    item_number         VARCHAR,
    item_description    TEXT,
    category_name       VARCHAR,
    is_anchor           BOOLEAN,
    final_score         NUMERIC,
    item_status         VARCHAR,
    item_risk           VARCHAR,
    proposed_action     VARCHAR
) LANGUAGE sql STABLE AS $$
    SELECT
        a.items_total,
        a.groups_detected,
        COUNT(DISTINCT r.inventory_item_id) OVER ()         AS items_involucrados,
        ROUND(AVG(CASE WHEN NOT r.is_anchor THEN r.final_score END)
              OVER ()::NUMERIC, 3)                          AS score_promedio,
        r.group_id,
        r.group_label,
        r.group_category,
        r.group_risk,
        r.group_size,
        r.inventory_item_id,
        r.item_number,
        r.item_description,
        r.category_name,
        r.is_anchor,
        r.final_score,
        r.item_status,
        r.item_risk,
        r.proposed_action
    FROM inv_similarity_results r
    JOIN inv_analysis_runs a
      ON a.request_id = r.request_id
    WHERE r.request_id = p_request_id
    ORDER BY
        r.group_id   ASC,
        r.is_anchor  DESC,
        r.final_score DESC NULLS LAST;
$$;

INT_JOB_ALL_INV_ITEMS_EXTRACT

-- ============================================================
-- Credenciales
-- ============================================================
-- Tabla OFC_CREDENTIALS: CREDENTIAL_NAME, HOST, USER, PASSWORD, STATUS, 5 ATRIBUTOS y los campos who

CREATE TABLE OFC_CREDENTIALS(
	-- Col. principales 
	CREDENTIAL_ID   SERIAl PRIMARY KEY,
    CREDENTIAL_NAME VARCHAR(100),
    HOST            TEXT,
    USERNAME        TEXT,
    USER_PASSWORD   TEXT,
    ESTATUS         VARCHAR(100),

    -- Campos WHO
    created_by      VARCHAR(100) DEFAULT current_user,   -- usuario de sesión
    created_at      TIMESTAMP    DEFAULT now(),          -- fecha/hora creación
    updated_by      VARCHAR(100) DEFAULT current_user,   -- última modificación
    is_active       BOOLEAN      DEFAULT TRUE,           -- eliminado lógico
	
	-- Atributos
	attribute1      VARCHAR(250),
	attribute2		VARCHAR(250),
	attribute3		VARCHAR(250),
	attribute4		VARCHAR(250),
	attribute5		VARCHAR(250)
);

-- ============================================================
-- Oracle Cloud REST API
-- ============================================================
-- Tabla OFC_REST_API: API_NAME, DESCRIPTION URI, STATUS, 5 ATRIBUTOS, CAMPOS WHO

CREATE TABLE OFC_REST_API(
	-- Col. principales
	API_NAME		VARCHAR(100),
	DESCRIPTION		VARCHAR(100),
	URI 			VARCHAR(100),
	ESTATUS			VARCHAR(100),
	
	-- Campos WHO
    created_by      VARCHAR(100) DEFAULT current_user,   -- usuario de sesión
    created_at      TIMESTAMP DEFAULT now(),             -- fecha/hora creación
    updated_by      VARCHAR(100) DEFAULT current_user,   -- última modificación
    is_active       BOOLEAN DEFAULT TRUE,                -- eliminado lógico
	
	-- Atributos
	attribute1		VARCHAR(250),
	attribute2		VARCHAR(250),
	attribute3		VARCHAR(250),
	attribute4		VARCHAR(250),
	attribute5		VARCHAR(250)
);

-- ============================================================
-- Buscar Empresas
-- ============================================================

CREATE TABLE FND_ENTERPRISES(
	ENTERPRISE_ID		SERIAL PRIMARY KEY,
    ENTERPRISE_CODE		VARCHAR(100),
    ENTERPRISE_NAME		VARCHAR(100),
    DESCRIPTION			VARCHAR(100),
    ESTATUS				VARCHAR(100),
	CREDENTIAL_ID       INTEGER,
    
    -- Campos WHO
    created_by      VARCHAR(100) DEFAULT current_user,   -- usuario de sesión
    created_at      TIMESTAMP DEFAULT now(),             -- fecha/hora creación
    updated_by      VARCHAR(100) DEFAULT current_user,   -- última modificación
    is_active       BOOLEAN DEFAULT TRUE,                -- eliminado lógico
	
	-- Atributos    
    attribute1		VARCHAR(250),
    attribute2		VARCHAR(250),
    attribute3		VARCHAR(250),
    attribute4		VARCHAR(250),
    attribute5		VARCHAR(250),
    FOREIGN KEY (CREDENTIAL_ID) REFERENCES OFC_CREDENTIALS(CREDENTIAL_ID),
);
CREATE INDEX ofc_credentials_uk UNIQUE, btree (credential_name, enterprise_id);

-- ============================================================
-- INSERT de Empresas
-- ============================================================
INSERT INTO FND_ENTERPRISES
(ENTERPRISE_CODE, ENTERPRISE_NAME, DESCRIPTION, ESTATUS, CREDENTIAL_ID)
VALUES 
('300000465216591', '001_MEX_ALSEA', 'Empresa 1', 'ACTIVE', 1);

-- ============================================================
-- Buscar Usuarios (Filtrando por Empresas)
-- ============================================================

  CREATE TABLE FND_USERS(
	USER_ID			SERIAL PRIMARY KEY,
	USER_NAME	    VARCHAR(100),
	FIRST_NAME		VARCHAR(100),
	LAST_NAME		VARCHAR(100),
	EMAIL			VARCHAR(100),
	DESCRIPTION		VARCHAR(100),
	ESTATUS			VARCHAR(100),
	ENTERPRISE_ID	INTEGER,

	-- Campos WHO
	created_by      VARCHAR(100) DEFAULT current_user,   -- usuario de sesión
	created_at      TIMESTAMP DEFAULT now(),             -- fecha/hora creación
	updated_by      VARCHAR(100) DEFAULT current_user,   -- última modificación
	is_active       BOOLEAN DEFAULT TRUE,                -- eliminado lógico
	
	-- Atributos
	attribute1		VARCHAR(250),
	attribute2		VARCHAR(250),
	attribute3		VARCHAR(250),
	attribute4		VARCHAR(250),
	attribute5		VARCHAR(250),
    FOREIGN KEY (ENTERPRISE_ID) REFERENCES FND_ENTERPRISES(ENTERPRISE_ID)
);

-- ============================================================
-- INSERT de Usuario
-- ============================================================
INSERT INTO FND_USERS
(USER_NAME, FIRST_NAME, LAST_NAME, EMAIL, DESCRIPTION, ESTATUS, ENTERPRISE_ID)
VALUES 
('Marc', 'Marco', 'Salmeron', 'marco.salmeron.condor@gmail.com', 'usuario para empresa MEX ALSEA', 'ACTIVE', 1);

-- ============================================================
-- Tabla de Process Config
-- ============================================================

CREATE TABLE FND_PROCESS_CONFIG (
    id_process SERIAL PRIMARY KEY,
    process_code VARCHAR(255) NOT NULL,
    ENTERPRISE_ID INTEGER NOT NULL,
	
	-- Campos WHO
	created_by      VARCHAR(100) DEFAULT current_user,   -- usuario de sesión
	created_at      TIMESTAMP DEFAULT now(),             -- fecha/hora creación
	updated_by      VARCHAR(100) DEFAULT current_user,   -- última modificación
	is_active       BOOLEAN DEFAULT TRUE,                -- eliminado lógico
	
	-- Atributos
	attribute1		VARCHAR(250),
	attribute2		VARCHAR(250),
	attribute3		VARCHAR(250),
	attribute4		VARCHAR(250),
	attribute5		VARCHAR(250),
	FOREIGN KEY (ENTERPRISE_ID) REFERENCES FND_ENTERPRISES (ENTERPRISE_ID)
);

-- ============================================================
-- Insert de Process Config (Nombre Job)
-- ============================================================

INSERT INTO process_config
(process_code, ENTERPRISE_ID, attribute1)
VALUES
('/oracle/apps/ess/custom/Integration/INV/Catalogos/,INT_JOB_ALL_INV_ITEMS_EXTRACT', 1, 'ExtractFileType=ALL');

-- ============================================================
-- Ejecutar Servicio
-- ============================================================
python -m agent_services.app.main

-- ============================================================
-- Entrar al contenedor
-- ============================================================
docker exec -it inventory_ia psql -U postgres -d inventory_ia

/agents/{enterprise_id}/bulkExport

{
  "ProcessCode": "INV-IA",
  "Parameters":{
    "InvOrganizationId": 200
  }

}

busca las credenciales a partir del enterprise_id
credencial
 nombre job a partir del process_Code
 bulkexpoert
   "inv,job_erp"
   200
   "EXPPORT_ALL"

   INVOCAM
   ESPERAS
   RECUPERZ EL ZIP
   GUARDAS EN TABLAS