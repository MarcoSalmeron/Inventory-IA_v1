# requirements:
# pip install oracledb sentence-transformers PyPDF2 python-dotenv

import json
import array
from sentence_transformers import SentenceTransformer
from datetime import datetime
import re
import os
import sys
import io
import warnings
import pdfplumber

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────

WALLET_DIR = r"C:\Development\Drive\Tools_Documents\WALLETS\Wallet_IK941X8FHJQMB71P"
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
warnings.filterwarnings("ignore")

DB_CONFIG = {
    "user":             "IA_STUDENT",
    "password":         ".tscEpEe}Q0H9Oym]>7+1",
    "dsn":              "ik941x8fhjqmb71p_low",        # nombre del TNS en tnsnames.ora
                                               # Ej: mydb_high, mydb_medium, mydb_low
    "config_dir":       WALLET_DIR,        # carpeta donde está el wallet
    "wallet_location":  WALLET_DIR,        # misma carpeta
    "wallet_password":  "A#sI4_8MUmB4I" # contraseña del wallet (si tiene)
}

MODELO_EMBEDDING = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
VERSION_DOC      = "2024.1"
CHUNK_SIZE      = 400



# ─────────────────────────────────────────────
# CLASE PRINCIPAL
# ─────────────────────────────────────────────
class PoliticasAeromexicoRAG:

    def __init__(self):
        print("Cargando modelo de embeddings...")
        self.model = SentenceTransformer(MODELO_EMBEDDING)
        self.conn  = None
        print("[OK]     Modelo cargado")

    def conectar(self):
        

        conn = oracledb.connect(
            user            = DB_CONFIG["user"],
            password        = DB_CONFIG["password"],
            dsn             = DB_CONFIG["dsn"],
            config_dir      = DB_CONFIG["config_dir"],
            wallet_location = DB_CONFIG["wallet_location"],
            wallet_password = DB_CONFIG.get("wallet_password")
        )
        print(f"Conectado a Oracle — versión: {conn.version}")
        self.conn = oracledb.connect(**DB_CONFIG)
        print("Conexión exitosa")

    def embedding(self, texto: str) -> array.array:
        vec = self.model.encode(texto, normalize_embeddings=True)
        return array.array('f', vec.tolist())

    # ── Limpiar tabla para reinsertar ────────────────────────
    def limpiar_tabla(self):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM politicas_aeromexico")
        self.conn.commit()
        cur.close()
        print("[DB]     Tabla limpiada - registros eliminados")

    # ── Leer PDF con encoding explícito ─────────────────────
    def extraer_pdf(self, pdf_path: str) -> list:
        paginas = []
        with pdfplumber.open(pdf_path) as pdf:
            print(f"[PDF]    {len(pdf.pages)} paginas encontradas")
            for i, page in enumerate(pdf.pages, 1):
                texto = page.extract_text()
                if texto and texto.strip():
                    # Asegurar UTF-8 limpio
                    texto = self._limpiar_encoding(texto)
                    paginas.append({"pagina": i, "texto": texto})
                    print(f"[PDF]    Pagina {i}: {len(texto)} chars")
        return paginas

    def _limpiar_encoding(self, texto: str) -> str:
        """Normaliza caracteres especiales del español."""
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

    # ── Chunking por secciones ───────────────────────────────
    def generar_chunks(self, paginas: list) -> list:
        TIPO_MAP = {
            "equipaje": "equipaje",     "check-in": "checkin",
            "abordaje": "checkin",      "cambios": "cambios",
            "cancelaciones": "cambios", "menores": "menores",
            "mascotas": "mascotas",     "club premier": "club_premier",
            "derechos": "derechos",     "documentacion": "documentacion"
        }

        def inferir_tipo(t):
            for k, v in TIPO_MAP.items():
                if k in t.lower():
                    return v
            return "general"

        def limpiar(texto):
            return '\n'.join([
                l for l in texto.split('\n')
                if "POLITICAS DE VUELO" not in l.upper()
                and "Politicas Oficiales" not in l
            ])

        texto_completo = "\n".join(limpiar(p["texto"]) for p in paginas)
        lineas  = texto_completo.split('\n')
        chunks  = []
        buffer  = []
        seccion = "General"
        subseccion = ""
        chunk_id = 1

        def guardar():
            nonlocal chunk_id
            contenido = '\n'.join(buffer).strip()
            if len(contenido) < 50:
                return
            prefijo = f"Política de Aeroméxico - {seccion} - {subseccion}:\n"
            contenido_enriquecido = prefijo + contenido
            chunks.append({
                "chunk_id":   f"POL-{chunk_id:03d}",
                "seccion":    seccion,
                "subseccion": subseccion,
                "contenido":  contenido,
                "metadata":   {
                    "tipo":  inferir_tipo(f"{seccion} {subseccion}"),
                    "chars": len(contenido)
                }
            })
            chunk_id += 1

        for linea in lineas:
            l = linea.strip()
            if not l:
                continue
            if re.match(r'^\d+\.\s+\S', l) and not re.match(r'^\d+\.\d+', l):
                guardar(); buffer = [l]; seccion = l; subseccion = ""
            elif re.match(r'^\d+\.\d+\s+\S', l):
                guardar(); buffer = [l]; subseccion = l
            else:
                buffer.append(l)
                if len('\n'.join(buffer)) > CHUNK_SIZE:
                    guardar(); buffer = buffer[-3:]

        guardar()
        print(f"[CHUNKS] {len(chunks)} chunks generados")
        for c in chunks:
            print(f"         {c['chunk_id']} | {c['subseccion'] or c['seccion']}")
        return chunks

    # ── Insertar chunks ──────────────────────────────────────
    def cargar(self, chunks: list):
        cur = self.conn.cursor()
        insertados = 0
        for chunk in chunks:
            # Verificar encoding antes de insertar
            contenido = chunk["contenido"]
            print(f"[CHECK]  {chunk['chunk_id']} muestra: {contenido[:60]!r}")

            cur.execute("""
                INSERT INTO politicas_aeromexico
                    (chunk_id, seccion, subseccion, contenido,
                     metadata, embedding, version_doc)
                VALUES (:1, :2, :3, :4, :5, :6, :7)
            """, [
                chunk["chunk_id"],
                chunk["seccion"],
                chunk["subseccion"],
                contenido,
                json.dumps(chunk["metadata"], ensure_ascii=False),
                self.embedding(contenido),
                VERSION_DOC
            ])
            insertados += 1
            print(f"[INSERT] {chunk['chunk_id']} - OK")

        self.conn.commit()
        cur.close()
        print(f"[OK]     {insertados} chunks insertados")

    # ── Búsqueda semántica ───────────────────────────────────
    def buscar(self, pregunta: str, top_k: int = 3) -> list:
        emb = self.embedding(pregunta)
        cur = self.conn.cursor()
        cur.execute("""
            SELECT chunk_id, seccion, subseccion, contenido, metadata,
                   VECTOR_DISTANCE(embedding, :1, COSINE) AS distancia
            FROM politicas_aeromexico
            ORDER BY distancia ASC
            FETCH FIRST :2 ROWS ONLY
        """, [emb, top_k])

        resultados = []
        for row in cur.fetchall():
            # Leer CLOB
            contenido = row[3].read() if hasattr(row[3], 'read') else row[3]

            # Fix encoding si viene corrupto desde Oracle
            if isinstance(contenido, str):
                try:
                    contenido = contenido.encode('latin-1').decode('utf-8')
                except (UnicodeDecodeError, UnicodeEncodeError):
                    pass

            # Metadata: Oracle 23ai puede devolver dict o str
            meta = row[4]
            if isinstance(meta, dict):
                metadata = meta
            elif isinstance(meta, str):
                metadata = json.loads(meta)
            else:
                metadata = {}

            resultados.append({
                "chunk_id":   row[0],
                "seccion":    row[1],
                "subseccion": row[2],
                "contenido":  contenido,
                "metadata":   metadata,
                "similitud":  round(1 - float(row[5]), 4)
            })
        cur.close()
        return resultados

    def mostrar_resultado(self, pregunta: str, top_k: int = 2):
        print(f"\n{'='*60}")
        print(f"[QUERY]  {pregunta}")
        print(f"{'='*60}")
        for i, r in enumerate(self.buscar(pregunta, top_k), 1):
            print(f"\n[#{i}] Similitud: {r['similitud']}")
            print(f"      Seccion  : {r['seccion']}")
            print(f"      Subsec   : {r['subseccion']}")
            print(f"      Contenido:\n{r['contenido']}")

    def cerrar(self):
        if self.conn:
            self.conn.close()
            print("[DB]     Conexion cerrada")