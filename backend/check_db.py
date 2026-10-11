"""Step 1 checkpoint: run `python check_db.py` from backend/."""
from app.db import get_conn

EXPECTED = {"repos", "files", "chunks", "symbols", "refs"}

with get_conn() as conn:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    ).fetchall()
    found = {r[0] for r in rows}
    print("tables:", sorted(found))
    print("OK" if EXPECTED <= found else f"MISSING: {EXPECTED - found}")
