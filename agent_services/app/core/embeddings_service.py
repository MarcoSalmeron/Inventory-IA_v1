from psycopg2.extras import execute_values
from .db_conn import get_conn
import csv

def insert_inv_items_raw(request_id, job_id, source_file, csv_path):
    """
    Inserta todas las filas del CSV Oracle en la tabla inv_items_raw.
    """
    print(f"{'='*30}\n-- insert (inv_items_raw) --\n{'='*30}")

    try:
        conn = get_conn()

        with conn.cursor() as cur:
            with open(csv_path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='|')

                rows = []
                for row in reader:
                    rows.append((
                        request_id,
                        job_id,
                        source_file,
                        row["P_INV_ORGANIZATION_ID"],
                        row["INVENTORY_ITEM_ID"],
                        row["ORGANIZATION_ID"],
                        row["ORGANIZATION_CODE"],
                        row["BUSINESS_UNIT_ID"],
                        row["BUSINESS_UNIT_NAME"],
                        row["LEGAL_ENTTITY_ID"],   # typo Oracle
                        row["MASTER_ORG_ID"],
                        row["ITEM_CLASS"],
                        row["ITEM_NUMBER"],
                        row["ITEM_DESCRIPTION"],
                        None,                      # long_description (no viene en CSV)
                        row["CATEGORY_NAME"],
                        row["ITEM_STATUS"],
                        row["ITEM_STATUS_NAME"],
                        row["ITEM_STATUS_DESCRIPTION"],
                        row["APPROVAL_STATUS"],
                        row["PRIMARY_UOM_VAL"],
                        None,                      # secondary_uom (no viene en CSV)
                        row["DIMENSION_UOM"],
                        row["WEIGHT_UOM"],
                        row["VOLUME_UOM"],
                        row["UNIT_WIDTH_QUANTITY"],
                        row["UNIT_LENGTH_QUANTITY"],
                        row["UNIT_HEIGHT_QUANTITY"],
                        row["UNIT_WEIGTH_QUANTITY"], # typo Oracle
                        row["UNIT_VOLUME_QUANTITY"],
                        row["PRIMARY_TRANSACTION_QUANTITY"],
                        row["INVENTORY_ITEM_FLAG"],
                        row["STOCK_ENABLED_FLAG"],
                        row["CUSTOMER_ORDER_FLAG"],
                        row["CUSTOMER_ORDER_ENABLED_FLAG"],
                        row["SHIPPABLE_FLAG"],
                        row["INVOICED_FLAG"],
                        row["PURCHASING_ITEM_FLAG"],
                        row["PURCHASING_ENABLED_FLAG"],
                        None,                      # purchasing_tax_code (no viene en CSV)
                        None, None, None, None,    # almacenaje, origen, tipo, proveedor
                        row["VERSION_ID"],
                        row["CREATION_DATE"],
                        row["LAST_UPDATE_DATE"],
                        row["CREATED_BY"],
                        row["LAST_UPDATED_BY"]
                    ))

            sql = """
            INSERT INTO inventory_ia.inv_items_raw (
                request_id, job_id, source_file,
                p_inv_organization_id, inventory_item_id, organization_id, organization_code,
                business_unit_id, business_unit_name, legal_entity_id, master_org_id, item_class,
                item_number, item_description, long_description, category_name,
                item_status, item_status_name, item_status_description, approval_status,
                primary_uom_val, secondary_uom, dimension_uom, weight_uom, volume_uom,
                unit_width_quantity, unit_length_quantity, unit_height_quantity,
                unit_weight_quantity, unit_volume_quantity, primary_transaction_qty,
                inventory_item_flag, stock_enabled_flag, customer_order_flag,
                customer_order_enabled_flag, shippable_flag, invoiced_flag,
                purchasing_item_flag, purchasing_enabled_flag, purchasing_tax_code,
                almacenaje, origen, tipo, proveedor,
                version_id, creation_date, last_update_date, created_by, last_updated_by
            )
            VALUES %s
            """

            execute_values(cur, sql, rows)
            conn.commit()
            
    except Exception as ex:
        raise ex
    
    finally:
        conn.close()

    print(f"{'='*30}\n-- insert (inv_items_raw) finalizado --\n{'='*30}")
