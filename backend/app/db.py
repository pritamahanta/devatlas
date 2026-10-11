import psycopg
from pgvector.psycopg import register_vector

from .config import settings


def get_conn():
    conn = psycopg.connect(settings.database_url)
    register_vector(conn)
    return conn
