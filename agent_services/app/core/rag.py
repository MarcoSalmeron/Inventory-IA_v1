import json
import array
from sentence_transformers import SentenceTransformer
from datetime import datetime
import re
import os
import sys
import io
import warnings
from agent_services.app.core.db_conn import get_conn
from dotenv import load_dotenv

load_dotenv(override=True)

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
warnings.filterwarnings("ignore")

MODELO_EMBEDDING = os.getenv("HF_MODEL", "all-mpnet-base-v2")


# ─────────────────────────────────────────────
# CLASE PRINCIPAL
# ─────────────────────────────────────────────
class InventoryEmbeddingsRAG:

    def __init__(self):
        print(f"\n{'=' * 30}\n[RAG] Cargando modelo de Embeddings (768 d)...\n{'=' * 30}\n")
        self.model = SentenceTransformer(MODELO_EMBEDDING)
        self.conn = get_conn()
        print(f"\n{'=' * 30}\n[OK] Modelo cargado con éxito\n{'=' * 30}\n")

    # ── Crear embeddings reformulado para pgvector ────────────────────────
    def embedding(self, texto: str) -> str:
        """Genera el vector y lo transforma al formato de cadena aceptado por pgvector '[f1,f2...]'"""
        # Cambiamos texto: list a texto: str porque el input de búsqueda o composite es un string individual.
        vec = self.model.encode(texto, normalize_embeddings=True)
        return json.dumps(vec.tolist())

    # ── Limpiar tabla para reinsertar ────────────────────────
    def limpiar_tabla(self):
        print(f"\n{'=' * 30}\n[DB] Limpiando Tabla inv_embeddings...\n{'=' * 30}\n")
        cur = self.conn.cursor()
        cur.execute("DELETE FROM inv_embeddings")
        self.conn.commit()
        cur.close()
        print(f"\n{'=' * 30}\n[DB] Tabla limpiada - registros eliminados\n{'=' * 30}\n")

    def _limpiar_encoding(self, texto: str) -> str:
        """Normaliza caracteres especiales del español."""
        if not texto:
            return texto
        try:
            texto = texto.encode('latin-1').decode('utf-8')
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass

        reemplazos = {
            'Ã³': 'ó', 'Ã©': 'é', 'Ã¡': 'á', 'Ã­': 'í', 'Ãº': 'ú',
            'Ã±': 'ñ', 'Ã': 'Ñ', 'Â¿': '¿', 'Â¡': '¡',
            'Ã ': 'à', 'Ã¼': 'ü', 'â€™': "'", 'â€œ': '"', 'â€': '"'
        }
        for corrupto, correcto in reemplazos.items():
            texto = texto.replace(corrupto, correcto)
        return texto

    # ── Insertar chunks y embeddings acoplados al DDL ──────────────────────────────────────
    def cargar_inv_embeddings(self, chunks: list, request_id: str, job_id: int):
        print(f"\n{'=' * 30}\n[DB] Insertando Chunks y Embeddings con Atributos de Boost\n{'=' * 30}\n")
        cur = self.conn.cursor()
        insertados = 0

        for chunk in chunks:
            meta = chunk["metadata"]
            descripcion_raw = meta.get("ITEM_DESCRIPTION", "")
            descripcion_norm = self._limpiar_encoding(descripcion_raw)

            # Construcción inteligente del composite usando los metadatos para mejorar la semántica
            categoria = meta.get('CATEGORY_NAME', '')
            uom = meta.get('PRIMARY_UOM_VAL', '')
            almacenaje = meta.get('ALMACENAJE', '')

            composite = f"{descripcion_norm} | {categoria} | {almacenaje}".strip(" | ")

            # Generar el vector en formato texto para pgvector
            vector_str = self.embedding(composite)

            cur.execute("""
                INSERT INTO inv_embeddings (
                    request_id, embedding_model, embedding_dimensions,
                    inventory_item_id, organization_code, business_unit_name,
                    category_name, item_number, item_status, primary_uom_val,
                    almacenaje, origen, tipo,
                    description_raw, description_normalized, composite_text,
                    embedding
                )
                VALUES (%s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s::vector)
                ON CONFLICT (request_id, inventory_item_id) DO NOTHING
            """, [
                request_id, MODELO_EMBEDDING, 768,
                meta.get("INVENTORY_ITEM_ID"), meta.get("ORGANIZATION_CODE"),
                meta.get("BUSINESS_UNIT_NAME"), categoria,
                meta.get("ITEM_NUMBER"), meta.get("ITEM_STATUS"), uom,
                almacenaje, meta.get("ORIGEN"), meta.get("TIPO"),  # Guardados para evitar JOINs en el boost
                descripcion_raw, descripcion_norm, composite,
                vector_str
            ])
            insertados += 1

        self.conn.commit()
        cur.close()
        print(f"\n{'=' * 30}\n[OK] {insertados} embeddings e índices guardados.\n{'=' * 30}\n")

    # ── Búsqueda semántica dinámica y acoplada ───────────────────────────────────
    def buscar(self,
               producto_texto: str,
               request_id: str,
               uom_origen: str = None,
               tipo_origen: str = None,
               origen_origen: str = None,
               category_filter: str = None,
               top_k: int = 3) -> list:
        """
        Ejecuta la búsqueda semántica vectorizada aplicando el operador <=> (distancia coseno).
        Filtra obligatoriamente por request_id y opcionalmente por category_name para aprovechar los índices.
        """
        print(f"\n{'=' * 30}\n[RAG] Busqueda Semantica de: {producto_texto}\n{'=' * 30}\n")

        # Generar embedding del target
        emb_str = self.embedding(producto_texto)
        cur = self.conn.cursor()

        # Query con filtros estructurados para PostgreSQL/pgvector
        query = """
            SELECT inventory_item_id, item_number, description_raw, category_name,
                   item_status, primary_uom_val, tipo, origen, organization_code, business_unit_name, almacenaje,
                   (embedding <=> %s::vector) AS distancia
            FROM inv_embeddings
            WHERE request_id = %s
        """
        params = [emb_str, request_id]

        # Filtro de partición previo para optimizar rendimiento HNSW
        if category_filter:
            query += " AND category_name = %s"
            params.append(category_filter)

        query += """
            ORDER BY distancia ASC
            FETCH FIRST %s ROWS ONLY
        """
        params.append(top_k)

        cur.execute(query, params)
        resultados = []

        for row in cur.fetchall():
            # Desestructuración de la fila de la base de datos
            inv_id, item_num, desc_raw, cat_name, status, cand_uom, cand_tipo, cand_origen, org_code, bu_name, alm = row[
                0:11]
            distancia = float(row[11])

            # En pgvector, el operador <=> retorna la distancia coseno (1 - similitud)
            cosine_score = round(1.0 - distancia, 4)

            # --- VALIDACIÓN DE BOOSTS DINÁMICOS ---
            # Se aplica el beneficio solo si coincide con las propiedades del ítem origen consultado
            uom_boost = 0.150 if cand_uom == uom_origen and uom_origen is not None else 0.0
            tipo_boost = 0.100 if cand_tipo == tipo_origen and tipo_origen is not None else 0.0
            origen_boost = 0.050 if cand_origen == origen_origen and origen_origen is not None else 0.0

            # --- REGLA DE PONDERACIÓN EXPLICITADA EN EL DDL ---
            # final_score = (cosine * 0.70) + uom_boost + tipo_boost + origen_boost
            final_score = round((cosine_score * 0.70) + uom_boost + tipo_boost + origen_boost, 4)

            item_data = {
                "inventory_item_id": inv_id,
                "item_number": item_num,
                "item_description": desc_raw,
                "category_name": cat_name,
                "item_status": status,
                "cosine_score": cosine_score,
                "uom_boost": uom_boost,
                "tipo_boost": tipo_boost,
                "origen_boost": origen_boost,
                "final_score": final_score
            }
            resultados.append(item_data)

            # Inserción en inv_similarity_results (Acoplado al 100% con las columnas de tu DDL)
            cur.execute("""
                INSERT INTO inv_similarity_results (
                    request_id, group_id, group_label, group_category, group_risk,
                    group_size, group_avg_score,
                    inventory_item_id, item_number, item_description, category_name,
                    is_anchor, cosine_score, uom_boost, tipo_boost, origen_boost, final_score,
                    item_status, organization_code, business_unit_name, primary_uom_val, almacenaje, origen, tipo
                )
                VALUES (%s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s,
                        FALSE, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (request_id, inventory_item_id) DO NOTHING
            """, [
                request_id, 1, "Grupo demo", cat_name, "medium",
                top_k, final_score,  # Cargamos final_score como score representativo en la demo
                inv_id, item_num, desc_raw, cat_name,
                cosine_score, uom_boost, tipo_boost, origen_boost, final_score,
                status, org_code, bu_name, cand_uom, alm, cand_origen, cand_tipo
            ])

        self.conn.commit()
        cur.close()
        return resultados

    def mostrar_resultado(self, producto: str, request_id: str, uom: str = None, tipo: str = None, origen: str = None,
                          category: str = None, top_k: int = 2):
        print(f"\n{'=' * 30}\n[Producto consultado] {producto}\n{'=' * 30}\n")
        res = self.buscar(producto, request_id, uom_origen=uom, tipo_origen=tipo, origen_origen=origen,
                          category_filter=category, top_k=top_k)
        for i, r in enumerate(res, 1):
            print(f"\n[#{i}] Final Score : {r['final_score']} (Cosine Base: {r['cosine_score']})")
            print(f"      Item Number : {r['item_number']}")
            print(f"      Descripción : {r['item_description']}")
            print(f"      Categoría   : {r['category_name']}")
            print(f"      Boosts      : UOM: {r['uom_boost']} | Tipo: {r['tipo_boost']} | Origen: {r['origen_boost']}")
            print(f"      Estado      : {r['item_status']}")

    def cerrar(self):
        if self.conn:
            self.conn.close()
            print(f"\n{'=' * 30}\n[DB] Conexión cerrada\n{'=' * 30}\n")