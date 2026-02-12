import sqlite3
import json
import os

DB_PATH = r'C:\ProgramData\PCP-Automation\data\nexus.db'

def verify_jobs(ids):
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    query = f"SELECT id, filename, status, raw_comments, metadata FROM jobs WHERE " + " OR ".join([f"filename LIKE '%{i}%'" for i in ids])
    
    try:
        cursor.execute(query)
        rows = cursor.fetchall()
        
        print(f"{'ID':<10} | {'Filename':<30} | {'Status':<10} | {'Comments'}")
        print("-" * 80)
        
        for row in rows:
            jid, fname, status, raw, meta_json = row
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except:
                meta = {}
            
            # The 'accepted_comments' is likely in metadata or raw_comments
            comments = meta.get('accepted_comments', raw or 'N/A')
            print(f"{jid:<10} | {fname[:30]:<30} | {status:<10} | {comments}")
            
    except Exception as e:
        print(f"Error executing query: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    test_ids = ["A25A05528", "A26101449", "A25A06432", "A25B02871", "A25A05515", "A25C01812", "A25C01833", "A25C07768"]
    verify_jobs(test_ids)
