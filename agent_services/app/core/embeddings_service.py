from psycopg2.extras import execute_values
from .db_conn import get_conn, update_analysis_run_org
import csv

def insert_inv_items_raw(request_id, job_id, source_file, csv_path):
    """
    Inserta todas las filas del CSV Oracle en la tabla inv_items_raw.
    """
    print(f"\n{'='*30}\n-- insert (inv_items_raw) --\n{'='*30}\n")

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
                        row.get("P_INV_ORGANIZATION_ID"),
                        row.get("INVENTORY_ITEM_ID"),
                        row.get("ORGANIZATION_ID"),
                        row.get("ORGANIZATION_CODE"),
                        row.get("BUSINESS_UNIT_ID"),
                        row.get("BUSINESS_UNIT_NAME"),
                        row.get("LEGAL_ENTTITY_ID"),
                        row.get("MASTER_ORG_ID"),
                        row.get("ITEM_CLASS"),
                        row.get("ITEM_NUMBER"),
                        row.get("ITEM_DESCRIPTION"),
                        None,  # long_description
                        row.get("CATEGORY_NAME"),
                        row.get("ITEM_STATUS"),
                        row.get("ITEM_STATUS_NAME"),
                        row.get("ITEM_STATUS_DESCRIPTION"),
                        row.get("APPROVAL_STATUS"),
                        row.get("PRIMARY_UOM_VAL"),
                        None,  # secondary_uom
                        row.get("DIMENSION_UOM"),
                        row.get("WEIGHT_UOM"),
                        row.get("VOLUME_UOM"),
                        row.get("UNIT_WIDTH_QUANTITY"),
                        row.get("UNIT_LENGTH_QUANTITY"),
                        row.get("UNIT_HEIGHT_QUANTITY"),
                        row.get("UNIT_WEIGTH_QUANTITY"),
                        row.get("UNIT_VOLUME_QUANTITY"),
                        row.get("PRIMARY_TRANSACTION_QUANTITY"),
                        row.get("INVENTORY_ITEM_FLAG"),
                        row.get("STOCK_ENABLED_FLAG"),
                        row.get("CUSTOMER_ORDER_FLAG"),
                        row.get("CUSTOMER_ORDER_ENABLED_FLAG"),
                        row.get("SHIPPABLE_FLAG"),
                        row.get("INVOICED_FLAG"),
                        row.get("PURCHASING_ITEM_FLAG"),
                        row.get("PURCHASING_ENABLED_FLAG"),
                        None,  # purchasing_tax_code
                        None,  # almacenaje
                        None,  # origen
                        None,  # tipo
                        None,  # proveedor
                        row.get("VERSION_ID"),
                        row.get("CREATION_DATE"),
                        row.get("LAST_UPDATE_DATE"),
                        row.get("CREATED_BY"),
                        row.get("LAST_UPDATED_BY")
                    ))

                if rows:
                    first = rows[0]  # (request_id, job_id, source_file, p_inv_org_id, inv_item_id, org_id, org_code, bu_id, bu_name, ...)

                    # Segundo paso del pipeline: actualizar la tabla de resultados de extraccion
                    update_analysis_run_org(
                        request_id=first[0],
                        organization_id=first[3],    # P_INV_ORGANIZATION_ID
                        organization_code=first[6],  # ORGANIZATION_CODE
                        business_unit_id=first[7],   # BUSINESS_UNIT_ID
                        business_unit_name=first[8], # BUSINESS_UNIT_NAME
                        status="EXTRACTED",
                    )

            sql = """
            INSERT INTO inv_items_raw (
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
