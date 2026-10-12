"""Step 3 checkpoint: python lookup_symbol.py <repo-name> <symbol>
Shows where a symbol is defined and which chunks call it."""
import sys

from app.db import get_conn

if len(sys.argv) != 3:
    sys.exit("usage: python lookup_symbol.py <repo-name> <symbol>")
repo, sym = sys.argv[1], sys.argv[2]

with get_conn() as conn:
    print(f"Definitions of {sym}:")
    for path, line, kind in conn.execute(
        "SELECT s.path, s.line, s.kind FROM symbols s JOIN repos r ON r.id = s.repo_id "
        "WHERE r.name = %s AND s.name = %s ORDER BY s.path, s.line", (repo, sym)):
        print(f"  {kind:<8} {path}:{line}")
    print(f"\nCalled from:")
    for path, s, e, parent, symbol in conn.execute(
        "SELECT c.path, c.start_line, c.end_line, c.parent, c.symbol FROM refs f "
        "JOIN chunks c ON c.id = f.caller_chunk_id JOIN repos r ON r.id = f.repo_id "
        "WHERE r.name = %s AND f.callee_name = %s ORDER BY c.path, c.start_line", (repo, sym)):
        qual = f"{parent}.{symbol}" if parent else symbol
        print(f"  {path}:{s}-{e}  {qual}")
