"""Diagnose Phase 2 merge duplication issue."""
import sqlite3, json, os

conn = sqlite3.connect("C:/ProgramData/PCP-Automation/data/nexus.db")
conn.row_factory = sqlite3.Row

# Get a specific envelope that's known to be problematic
rows = conn.execute(
    "SELECT filename, file_path, metadata FROM jobs WHERE service_type='PROJECT_2' ORDER BY created_at DESC LIMIT 5"
).fetchall()

for row in rows:
    meta = json.loads(row['metadata']) if row['metadata'] else {}
    env = meta.get('envelope', '?')
    merged = meta.get('merged_parts', [])
    count = meta.get('part_count', 0)
    fp = row['file_path'] or ''
    
    print(f"\n{'='*60}")
    print(f"Envelope: {env}")
    print(f"Output: {row['filename']}")
    print(f"Part count: {count}")
    print(f"merged_parts ({len(merged)}): {merged}")
    
    # Count actual pages in output PDF
    try:
        from PyPDF2 import PdfReader
        if os.path.isfile(fp):
            pages = len(PdfReader(fp).pages)
            print(f"Actual output pages: {pages}")
    except Exception as e:
        print(f"Page count error: {e}")
    
    # List actual source files in the output directory
    output_dir = os.path.dirname(fp) if fp else ''
    if output_dir and os.path.isdir(output_dir):
        all_files = os.listdir(output_dir)
        source_files = [f for f in all_files if f.startswith(f"P2_{env}")]
        print(f"\nActual source files on disk ({len(source_files)}):")
        for sf in sorted(source_files):
            sfp = os.path.join(output_dir, sf)
            try:
                sp = len(PdfReader(sfp).pages)
                print(f"  {sf} ({sp} pages)")
            except:
                print(f"  {sf} (? pages)")

conn.close()
