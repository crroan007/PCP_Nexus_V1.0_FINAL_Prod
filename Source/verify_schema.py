import sqlite3
import os

def verify():
    try:
        db_path = r"C:\ProgramData\PCP-Automation\data\nexus.db"
        if not os.path.exists(db_path):
            print(f"DB not found at {db_path}")
            return

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get Tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Found Tables: {[t[0] for t in tables]}")
        
        md_content = "# Database Schema Guide\n\n"
        
        for t in tables:
            table_name = t[0]
            md_content += f"## Table: `{table_name}`\n"
            
            # Get Info
            cursor.execute(f"PRAGMA table_info({table_name})")
            cols = cursor.fetchall()
            
            md_content += "| CID | Name | Type | PK |\n|---|---|---|---|\n"
            for c in cols:
                pk_mark = "KEY" if c[5] else ""
                md_content += f"| {c[0]} | **{c[1]}** | {c[2]} | {pk_mark} |\n"
            md_content += "\n"
            
        conn.close()
        
        # Save verification artifact
        with open("schema_verification_result.md", "w", encoding="utf-8") as f:
            f.write(md_content)
            
        print("SUCCESS: Schema generated and saved to schema_verification_result.md")

    except Exception as ex:
        print(f"ERROR: {ex}")

if __name__ == "__main__":
    verify()
