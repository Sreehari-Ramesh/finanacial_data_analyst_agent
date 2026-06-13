"""Print schema for a range of tables in the connected SQL Server database.

Usage
-----
  python test_schema.py              # list all table names with numbers
  python test_schema.py 1 10         # print schema for tables 1-10
  python test_schema.py 5            # print schema for table #5 only
  python test_schema.py --list       # just list all table names with numbers
  python test_schema.py --txt        # export compact schema text file (non-empty tables only)
  python test_schema.py --txt out.txt  # export to a custom filename
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import inspect as sa_inspect, text
from config import get_db_engine, DB_SERVER, DB_NAME


def get_engine_and_tables():
    print(f"\nConnecting to: {DB_SERVER} / {DB_NAME}")
    engine = get_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("Connection OK\n")
    inspector = sa_inspect(engine)
    tables = inspector.get_table_names()
    return engine, inspector, tables


def list_tables(tables: list):
    print(f"{'#':<6} {'Table name'}")
    print("-" * 50)
    for i, tbl in enumerate(tables, 1):
        print(f"{i:<6} {tbl}")
    print(f"\nTotal: {len(tables)} tables")


def _get_row_count(engine, tbl: str) -> int:
    with engine.connect() as conn:
        try:
            return conn.execute(text(f"SELECT COUNT(*) FROM [{tbl}]")).scalar() or 0
        except Exception:
            return 0


def _build_table_data(inspector, tbl: str) -> dict:
    """Return schema info dict for one table (columns + indexes)."""
    pk_cols = set(inspector.get_pk_constraint(tbl).get("constrained_columns", []))
    fk_lookup: dict = {}
    for fk in inspector.get_foreign_keys(tbl):
        for local, ref in zip(fk["constrained_columns"], fk["referred_columns"]):
            fk_lookup[local] = f"{fk['referred_table']}.{ref}"

    columns = []
    for col in inspector.get_columns(tbl):
        name     = col["name"]
        dtype    = str(col["type"])
        nullable = "NULL" if col.get("nullable", True) else "NOT NULL"
        flags    = []
        if name in pk_cols:
            flags.append("PK")
        if name in fk_lookup:
            flags.append(f"FK -> {fk_lookup[name]}")
        columns.append({
            "name": name, "type": dtype,
            "nullable": nullable, "flags": ", ".join(flags),
        })

    indexes = []
    for idx in inspector.get_indexes(tbl):
        unique = "UNIQUE " if idx.get("unique") else ""
        cols   = ", ".join(idx["column_names"] or [])
        indexes.append(f"{unique}{idx['name']}  ({cols})")

    return {"columns": columns, "indexes": indexes}


def print_table_schema(engine, inspector, tbl: str, index: int):
    pk_cols = set(inspector.get_pk_constraint(tbl).get("constrained_columns", []))
    fk_lookup: dict = {}
    for fk in inspector.get_foreign_keys(tbl):
        for local, ref in zip(fk["constrained_columns"], fk["referred_columns"]):
            fk_lookup[local] = f"{fk['referred_table']}.{ref}"

    with engine.connect() as conn:
        try:
            row_count = conn.execute(text(f"SELECT COUNT(*) FROM [{tbl}]")).scalar()
        except Exception:
            row_count = "N/A"

    print(f"[{index}] TABLE: {tbl}  ({row_count} rows)")
    print("-" * 60)

    for col in inspector.get_columns(tbl):
        name     = col["name"]
        dtype    = str(col["type"])
        nullable = "NULL" if col.get("nullable", True) else "NOT NULL"
        flags    = []
        if name in pk_cols:
            flags.append("PK")
        if name in fk_lookup:
            flags.append(f"FK -> {fk_lookup[name]}")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        print(f"  {name:<40} {dtype:<20} {nullable}{flag_str}")

    indexes = inspector.get_indexes(tbl)
    if indexes:
        print()
        for idx in indexes:
            unique = "UNIQUE " if idx.get("unique") else ""
            cols   = ", ".join(idx["column_names"] or [])
            print(f"  INDEX {unique}{idx['name']}  ({cols})")

    print()


# ── Text export ───────────────────────────────────────────────────────────────

def export_txt(engine, inspector, tables: list, output_file: str = "schema.txt"):
    print("Scanning tables (skipping empty ones)...")
    non_empty = []
    for tbl in tables:
        count = _get_row_count(engine, tbl)
        if count > 0:
            non_empty.append((tbl, count))
            print(f"  + {tbl:<45} {count:>10,} rows")
        else:
            print(f"  - {tbl:<45}  (empty, skipped)")

    print(f"\n{len(non_empty)} tables with data out of {len(tables)} total")
    print("Writing schema file...")

    lines = []
    for tbl, row_count in non_empty:
        data = _build_table_data(inspector, tbl)
        lines.append(f"TABLE: {tbl} ({row_count:,} rows)")
        for col in data["columns"]:
            notes = f"  [{col['flags']}]" if col["flags"] else ""
            lines.append(f"  {col['name']} {col['type']} {col['nullable']}{notes}")
        lines.append("")   # blank line between tables

    Path(output_file).write_text("\n".join(lines), encoding="utf-8")
    print(f"Schema saved -> {output_file}  ({len(lines):,} lines, {len(non_empty)} tables)")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    engine, inspector, tables = get_engine_and_tables()
    total = len(tables)
    print(f"Total tables in DB: {total}\n")

    # list only
    if not args or "--list" in args:
        list_tables(tables)
        if not args:
            print("\nTip: python test_schema.py 1 10    -> print schema for tables 1-10")
            print("     python test_schema.py --pdf    -> export schema PDF (non-empty tables only)")
        return

    # text export
    if "--txt" in args:
        remaining = [a for a in args if a != "--txt"]
        out_file  = remaining[0] if remaining else f"schema_{DB_NAME}.txt"
        export_txt(engine, inspector, tables, out_file)
        return

    # range print
    try:
        if len(args) == 1:
            start = end = int(args[0])
        else:
            start, end = int(args[0]), int(args[1])
    except ValueError:
        print("Usage: python test_schema.py [start] [end]")
        print("Example: python test_schema.py 1 10")
        sys.exit(1)

    start = max(1, start)
    end   = min(total, end)

    if start > end:
        print(f"Invalid range {start}-{end}. DB has {total} tables.")
        sys.exit(1)

    selected = tables[start - 1 : end]
    print(f"Showing tables {start}-{end}  ({len(selected)} of {total})\n")
    print("=" * 80)
    for i, tbl in enumerate(selected, start=start):
        print_table_schema(engine, inspector, tbl, i)
    print("=" * 80)
    print(f"Done. Printed {len(selected)} table(s) [{start}-{end}].")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)
