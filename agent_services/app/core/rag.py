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

MODELO_EMBEDDING = os.getenv("HF_MODEL")

# ─────────────────────────────────────────────
# CLASE PRINCIPAL
# ─────────────────────────────────────────────
class InventoryEmbeddingsRAG:

    def __init__(self):
        print(f"\n{'='*30}\n[RAG] Cargando modelo de Embeddings...\n{'='*30}\n")
        self.model = SentenceTransformer(MODELO_EMBEDDING)
        self.conn = get_conn()
        print(f"\n{'='*30}\n[OK] Modelo cargado\n{'='*30}\n")

    # ── Crear embeddings ────────────────────────
    def embedding(self, texto: list) -> array.array:
        print(f"\n{'=' * 30}\n[RAG] Creando Embeddings...\n{'=' * 30}\n")
        vec = self.model.encode(texto, normalize_embeddings=True)
        return array.array('f', vec.tolist())

    # ── Limpiar tabla para reinsertar ────────────────────────
    def limpiar_tabla(self):
        print(f"\n{'=' * 30}\n[DB] Limpiando Tabla inv_embeddings...\n{'=' * 30}\n")
        cur = self.conn.cursor()
        cur.execute("DELETE FROM inv_embeddings")
        self.conn.commit()
        cur.close()
        print(f"\n{'='*30}\n[DB] Tabla limpiada - registros eliminados\n{'='*30}\n")

    def _limpiar_encoding(self, texto: str) -> str:
        """Normaliza caracteres especiales del español."""
        print(f"\n{'=' * 30}\n[DB] Limpiando Encoding\n{'=' * 30}\n")
        if not texto:
            return texto
        try:
            # Intentar fix de latin-1 mal interpretado como utf-8
            texto = texto.encode('latin-1').decode('utf-8')
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass

        # Reemplazos manuales de caracteres comunes corruptos
        reemplazos = {
            'Ã³': 'ó', 'Ã©': 'é', 'Ã¡': 'á', 'Ã­': 'í', 'Ãº': 'ú',
            'Ã±': 'ñ', 'Ã': 'Ñ', 'Â¿': '¿', 'Â¡': '¡',
            'Ã ': 'à', 'Ã¼': 'ü', 'â€™': "'", 'â€œ': '"', 'â€': '"'
        }
        for corrupto, correcto in reemplazos.items():
            texto = texto.replace(corrupto, correcto)
        return texto

    # ── Insertar chunks y embeddings ──────────────────────────────────────
    def cargar_inv_embeddings(self, chunks: list, request_id: str, job_id: int):
        print(f"\n{'=' * 30}\n[DB] Insertando Chunks y Embeddings\n{'=' * 30}\n")
        cur = self.conn.cursor()
        insertados = 0
        for chunk in chunks:
            meta = chunk["metadata"]
            descripcion_raw = meta.get("ITEM_DESCRIPTION", "")
            descripcion_norm = self._limpiar_encoding(descripcion_raw)
            composite = f"{descripcion_norm} | {meta.get('CATEGORY_NAME', '')} | {meta.get('PRIMARY_UOM_VAL', '')}"

            vector = self.embedding(composite)  # array/pgvector

            cur.execute("""
                INSERT INTO inv_embeddings (
                    request_id, embedding_model, embedding_dimensions,
                    inventory_item_id, organization_code, business_unit_name,
                    category_name, item_number, item_status, primary_uom_val,
                    description_raw, description_normalized, composite_text,
                    embedding
                )
                VALUES (%s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s)
                ON CONFLICT (request_id, inventory_item_id) DO NOTHING
            """, [
                request_id, MODELO_EMBEDDING, 768,
                meta.get("INVENTORY_ITEM_ID"), meta.get("ORGANIZATION_CODE"),
                meta.get("BUSINESS_UNIT_NAME"), meta.get("CATEGORY_NAME"),
                meta.get("ITEM_NUMBER"), meta.get("ITEM_STATUS"),
                meta.get("PRIMARY_UOM_VAL"),
                descripcion_raw, descripcion_norm, composite,
                vector
            ])
            insertados += 1
            print(f"[INSERT] {meta.get('INVENTORY_ITEM_ID')} - OK")

        self.conn.commit()
        cur.close()
        print(f"\n{'='*30}\n[OK] {insertados} embeddings insertados\n{'='*30}\n")

    # ── Búsqueda semántica ───────────────────────────────────
    def buscar(self, producto: str, request_id: str, top_k: int = 3) -> list:
        print(f"\n{'=' * 30}\n[RAG] Busqueda Semantica de {producto}\n{'=' * 30}\n")
        emb = self.embedding(producto)
        cur = self.conn.cursor()
        cur.execute("""
            SELECT inventory_item_id, item_number, description_raw, category_name,
                   item_status, primary_uom_val, tipo, origen,
                   VECTOR_DISTANCE(embedding, :1, COSINE) AS distancia
            FROM inv_embeddings
            ORDER BY distancia ASC
            FETCH FIRST :2 ROWS ONLY
        """, [emb, top_k])

        resultados = []
        for row in cur.fetchall():
            cosine_score = 1 - float(row[8])
            uom_boost = 0.15 if row[5] == "SER" else 0.0
            tipo_boost = 0.10 if row[6] else 0.0
            origen_boost = 0.05 if row[7] else 0.0
            final_score = round(cosine_score + uom_boost + tipo_boost + origen_boost, 4)

            resultados.append({
                "inventory_item_id": row[0],
                "item_number": row[1],
                "item_description": row[2],
                "category_name": row[3],
                "item_status": row[4],
                "cosine_score": round(cosine_score, 4),
                "uom_boost": uom_boost,
                "tipo_boost": tipo_boost,
                "origen_boost": origen_boost,
                "final_score": final_score
            })

            # Inserción en inv_similarity_results
            cur.execute("""
                INSERT INTO inv_similarity_results (
                    request_id, group_id, group_label, group_category, group_risk,
                    group_size, group_avg_score,
                    inventory_item_id, item_number, item_description, category_name,
                    is_anchor, cosine_score, uom_boost, tipo_boost, origen_boost, final_score,
                    item_status
                )
                VALUES (:1, :2, :3, :4, :5,
                        :6, :7,
                        :8, :9, :10, :11,
                        FALSE, :12, :13, :14, :15, :16,
                        :17)
                ON CONFLICT (request_id, inventory_item_id) DO NOTHING
            """, [
                request_id, 1, "Grupo demo", row[3], "medium",
                top_k, cosine_score,
                row[0], row[1], row[2], row[3],
                cosine_score, uom_boost, tipo_boost, origen_boost, final_score,
                row[4]
            ])

        self.conn.commit()
        cur.close()
        return resultados

    def mostrar_resultado(self, producto: str, request_id: str, top_k: int = 2):
        print(f"\n{'=' * 30}\n[Producto] {producto}\n{'=' * 30}\n")
        for i, r in enumerate(self.buscar(producto, request_id, top_k), 1):
            print(f"\n[#{i}] Final Score : {r['final_score']}")
            print(f"      Item Number : {r['item_number']}")
            print(f"      Descripción : {r['item_description']}")
            print(f"      Categoría   : {r['category_name']}")
            print(f"      UOM         : {r['uom_boost']} (boost aplicado)")
            print(f"      Estado      : {r['item_status']}")

    def cerrar(self):
        if self.conn:
            self.conn.close()
            print(f"\n{'='*30}\n[DB] Conexion cerrada\n{'='*30}\n")