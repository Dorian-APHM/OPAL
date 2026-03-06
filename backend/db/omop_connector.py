"""
Dynamic connection to external OMOP CDM PostgreSQL databases.
"""
import psycopg2
from psycopg2.extras import DictCursor


def get_omop_connection(host: str, port: int, dbname: str, user: str, password: str):
    """
    Open a psycopg2 connection to an OMOP CDM database.
    Returns a connection object.
    """
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        connect_timeout=10,
    )


def test_omop_connection(host: str, port: int, dbname: str, user: str, password: str) -> dict:
    """
    Test connectivity to an OMOP CDM database.
    Returns a dict with success status and message.
    """
    try:
        conn = get_omop_connection(host, port, dbname, user, password)
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT 1")
        conn.close()
        return {"success": True, "message": "Connection successful"}
    except Exception as e:
        return {"success": False, "message": str(e)}
