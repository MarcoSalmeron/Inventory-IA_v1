import os
import zipfile
import csv
import io
import tempfile
from pathlib import Path
from agent_services.app.core.embeddings_service import insert_inv_items_raw

from dotenv import load_dotenv

load_dotenv(override=True)

try:
    print(f'\n{"#"*30}\n---- INVENTORY SERVICE ----\n{"#"*30}\n')

    DOWNLOAD_DIR = Path(os.getenv("SOAP_DOWNLOAD_DIR", "downloads"))

    if DOWNLOAD_DIR:
        print(f"\n{'='*30}\n-- Directorio de descarga encontrado --\n{'='*30}\n")
        print(f"Directorio: {DOWNLOAD_DIR.resolve()}")
    else:
        raise Exception("Directorio de descarga no encontrado")

except Exception as ex:
    raise ex

def _row_to_text(row: dict) -> str:
    """Convierte una fila del CSV a texto plano para vectorización."""
    parts = [f"{key}: {value}" for key, value in row.items() if value and str(value).strip()]
    return " | ".join(parts)


def process_inventory_zip(zip_path: Path, request_id: int, job_id: int) -> list[dict]:
    """
    Lee el ZIP de inventario, extrae y parsea los archivos CSV,
    inserta cada CSV en la tabla inv_items_raw usando insert_inv_items_raw,
    elimina el ZIP y retorna una lista de chunks listos para vectorizar.

    Parámetros:
      - zip_path: Path al archivo ZIP
      - request_id: id del request para la inserción
      - job_id: id del job para la inserción
    """
    print(f'\n{"="*30}\n-- iniciando process_inventory_zip --\n{"="*30}\n')

    if not zip_path.exists():
        raise FileNotFoundError(f"ZIP no encontrado: {zip_path.resolve()}")

    chunks = []

    # Abrimos el ZIP
    with zipfile.ZipFile(zip_path, 'r') as zf:
        file_names = zf.namelist()
        print(f"Archivos en el ZIP: {file_names}")

        for file_name in file_names:
            # Solo procesar archivos CSV o de texto
            if not (file_name.lower().endswith('.csv') or file_name.lower().endswith('.txt')):
                print(f"Saltando archivo no CSV: {file_name}")
                continue

            print(f"\n{'='*30}\n-- Procesando: {file_name} --\n{'='*30}\n")

            # Leemos el contenido del archivo dentro del ZIP
            with zf.open(file_name) as f:
                content_bytes = f.read()
                # Intentamos detectar encoding utf-8, si falla usamos replace
                content = content_bytes.decode('utf-8', errors='replace')

            # Guardamos el CSV en un archivo temporal para que insert_inv_items_raw lo pueda leer
            # (insert_inv_items_raw espera una ruta de archivo)
            with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.csv', encoding='utf-8', newline='') as tmp:
                tmp_path = Path(tmp.name)
                # Si el CSV original usa '|' como delimitador, lo respetamos.
                # Para mantener el contenido tal cual, escribimos el texto leído.
                tmp.write(content)
                tmp.flush()

            try:
                # Llamada a la función que inserta en la tabla
                # insert_inv_items_raw(request_id, job_id, source_file, csv_path)
                print(f"Llamando a insert_inv_items_raw para {file_name} -> {tmp_path}")
                insert_inv_items_raw(request_id, job_id, file_name, str(tmp_path))

                # Además generamos los chunks para vectorización (igual que antes)
                reader = csv.DictReader(io.StringIO(content), delimiter='|')  # usar '|' si ese es el delimitador real
                for i, row in enumerate(reader):
                    text = _row_to_text(row)
                    if not text.strip():
                        continue
                    chunks.append({
                        "text": text,
                        "metadata": {
                            "source_file": file_name,
                            "row_index": i,
                            **dict(row)
                        }
                    })

            finally:
                # Borramos el archivo temporal
                try:
                    tmp_path.unlink()
                    print(f"Archivo temporal eliminado: {tmp_path}")
                except Exception as e:
                    print(f"No se pudo eliminar el temporal {tmp_path}: {e}")

    print(f"Total de chunks generados: {len(chunks)}")

    # Eliminar el ZIP después de procesar
    try:
        zip_path.unlink()
        print(f"ZIP eliminado: {zip_path.resolve()}")
    except Exception as e:
        print(f"No se pudo eliminar el ZIP {zip_path}: {e}")

    return chunks
