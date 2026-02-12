"""Deep diagnostic: check actual Phase 2 metadata AND file system for this run."""
import sqlite3, json, os, glob

conn = sqlite3.connect("C:/ProgramData/PCP-Automation/data/nexus.db")
conn.row_factory = sqlite3.Row

# Get first 3 Phase 2 envelopes
rows = conn.execute(
    "SELECT filename, file_path, metadata FROM jobs WHERE service_type='PROJECT_2' ORDER BY created_at DESC LIMIT 3"
).fetchall()

for row in rows:
    meta = json.loads(row['metadata']) if row['metadata'] else {}
    env = meta.get('envelope', '?')
    fp = row['file_path'] or ''
    output_dir = os.path.dirname(fp) if fp else ''
    
    print(f"\n{'='*70}")
    print(f"Envelope: {env}")
    print(f"Output: {row['filename']}")
    print(f"Output path: {fp}")
    print(f"File exists: {os.path.isfile(fp)}")
    
    # Page count
    try:
        from PyPDF2 import PdfReader
        if os.path.isfile(fp):
            print(f"Output pages: {len(PdfReader(fp).pages)}")
    except Exception as e:
        print(f"Page count error: {e}")
    
    # All metadata keys
    print(f"\nMetadata keys: {list(meta.keys())}")
    print(f"merged_parts ({len(meta.get('merged_parts',[]))}): {meta.get('merged_parts', [])}")
    print(f"part_count: {meta.get('part_count')}")
    print(f"constituent_docs: {meta.get('constituent_docs')}")
    print(f"classification: {meta.get('classification')}")
    
    # What's actually in the output directory?
    if output_dir and os.path.isdir(output_dir):
        all_files = os.listdir(output_dir)
        print(f"\nAll files in output dir ({len(all_files)}):")
        for f in sorted(all_files)[:30]:
            fsize = os.path.getsize(os.path.join(output_dir, f))
            print(f"  {f} ({fsize:,} bytes)")
        if len(all_files) > 30:
            print(f"  ... and {len(all_files) - 30} more")

conn.close()
