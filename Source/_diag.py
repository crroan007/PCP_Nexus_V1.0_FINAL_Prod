import sqlite3, json
conn = sqlite3.connect('C:/ProgramData/PCP-Automation/data/nexus.db')
c = conn.cursor()

# Check a few envelopes that show doc_0/doc_1 pattern
for env in ['110868011', '110883395', '110842951', '110860999', '110948043']:
    c.execute("SELECT id, filename, status, metadata FROM jobs WHERE metadata LIKE ?", (f'%{env}%',))
    rows = c.fetchall()
    print(f"=== Envelope {env} ({len(rows)} jobs) ===")
    for r in rows:
        meta = json.loads(r[3]) if r[3] else {}
        print(f"  Job #{r[0]} | {r[1]} | status={r[2]}")
        print(f"    sources: {meta.get('source_documents', [])}")
        print(f"    lead_doc: {meta.get('lead_doc', 'N/A')}")
        print()

conn.close()
