import sqlite3, json

conn = sqlite3.connect("C:/ProgramData/PCP-Automation/data/nexus.db")
conn.row_factory = sqlite3.Row

row = conn.execute("SELECT metadata, filename, file_path FROM jobs WHERE service_type='PROJECT_2' LIMIT 1").fetchone()
if row:
    meta = json.loads(row['metadata']) if row['metadata'] else {}
    print("=== METADATA KEYS ===")
    print(list(meta.keys()))
    print()
    print("=== constituent_docs ===")
    print(meta.get('constituent_docs', 'NOT FOUND'))
    print()
    print("=== merged_parts ===")
    print(meta.get('merged_parts', 'NOT FOUND'))
    print()
    print("=== filename ===")
    print(row['filename'])
    print()
    print("=== file_path ===")
    print(row['file_path'])
    print()
    print("=== FULL METADATA (first 2000 chars) ===")
    print(json.dumps(meta, indent=2)[:2000])
else:
    print("No PROJECT_2 jobs found")

conn.close()
