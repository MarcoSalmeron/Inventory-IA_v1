import psycopg2

# Conectar a la base de datos
def get_conn():
    return psycopg2.connect("postgresql://postgres:SalRam021@localhost:5432/inventory_ia")

