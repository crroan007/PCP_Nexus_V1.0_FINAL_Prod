import sqlite3, json, os

conn = sqlite3.connect("C:/ProgramData/PCP-Automation/data/nexus.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT filename, file_path, status, original_source, metadata FROM jobs WHERE service_type=? ORDER BY created_at", ("AFFIDAVITS",)).fetchall()

print(f"Phase 1 jobs: {len(rows)}")
print("=" * 90)
for r in rows:
    fp = r['file_path'] or ''
    exists = os.path.isfile(fp) if fp else False
    pages = 0
    if exists:
        try:
            from PyPDF2 import PdfReader
            pages = len(PdfReader(fp).pages)
        except: pass
    meta = json.loads(r['metadata']) if r['metadata'] else {}
    env = meta.get('envelope', '?')
    status = r['status']
    fname = r['filename']
    print(f"  {status:10s} | {fname:35s} | Env: {env:12s} | Exists: {'YES' if exists else 'NO':3s} | Pages: {pages}")

conn.close()
