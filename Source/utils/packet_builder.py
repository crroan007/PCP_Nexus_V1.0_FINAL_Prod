import os
import fitz  # PyMuPDF
from core.secure_config import conf

class PacketBuilder:
    """
    Phase 2 Component: PacketBuilder
    Responsibility: Merge multiple PDFs into a single "Packet".
    Logic: 
    1. Takes a list of file paths.
    2. Validates they exist.
    3. Merges them in order.
    4. Saves to 'Shadow' or 'Production' based on Config.
    """
    def __init__(self):
        self.shadow_mode = conf.get("phase2.shadow_mode_enabled", True)
        self.output_root = conf.get("paths.output", ".")
        self.shadow_root = conf.get("phase2.shadow_folder", os.path.join(self.output_root, "Shadow"))
        
        if self.shadow_mode:
            os.makedirs(self.shadow_root, exist_ok=True)

    def merge_files(self, file_list, output_filename):
        """
        Merges list of PDFs.
        file_list: List of absolute paths.
        output_filename: Desired name (e.g., 'Merged_Case123.pdf')
        Returns: (success, final_path)
        """
        if not file_list:
            return False, "No files provided"

        try:
            doc = fitz.open()
            for f in file_list:
                if os.path.exists(f):
                    try:
                        with fitz.open(f) as src:
                            doc.insert_pdf(src)
                    except Exception as e:
                        print(f"[PacketBuilder] Error reading {f}: {e}")
                        return False, f"Corrupt input: {os.path.basename(f)}"
                else:
                    return False, f"File not found: {f}"

            # Determine Output Path
            if self.shadow_mode:
                final_path = os.path.join(self.shadow_root, output_filename)
                print(f"[PacketBuilder] SHADOW MODE: Saving to {final_path}")
            else:
                final_path = os.path.join(self.output_root, output_filename)

            doc.save(final_path)
            doc.close()
            return True, final_path

        except Exception as e:
            return False, str(e)

    def run_cycle(self):
        from core.job_manager import job_manager
        
        # 1. Fetch Candidates (No Atomic Lock yet, we need to Group first)
        # We query ALL READY_TO_MERGE jobs to find groups.
        # This is safe because Hunter commits them transactionally.
        try:
            conn = job_manager._get_conn() # Helper access
            cursor = conn.cursor()
            cursor.execute("SELECT id, file_path, original_source, filename FROM jobs WHERE status='READY_TO_MERGE'")
            rows = cursor.fetchall()
            conn.close()
        except: return

        if not rows: return

        # 2. Group by Envelope
        groups = {}
        for row in rows:
            jid, path, src, fname = row
            # Extract Envelope ID: "Tyler: 12345"
            import re
            match = re.search(r"(\d+)", src)
            envelope_id = match.group(1) if match else "UNKNOWN"
            
            if envelope_id not in groups:
                 groups[envelope_id] = []
            groups[envelope_id].append({'id': jid, 'path': path, 'src': src, 'name': fname})

        # 3. Process Groups
        for env_id, jobs in groups.items():
            if len(jobs) < 2:
                # Still waiting for siblings? Or a single file marked as Merge (Hunter logic should prevent this)?
                # Hunter sets READY_TO_MERGE only if count > 1.
                # If only 1 is here, maybe others are processing?
                # BUT Hunter uses Two-Phase Commit. All should be here.
                # It might be a residual failure. Logic: Process anyway or wait?
                # Decision: Wait (Skip). It might be an orphan fixable by manual review.
                continue
                
            print(f"[PacketBuilder] Merging Envelope {env_id} ({len(jobs)} files)...")
            
            # Sort: Main Lead Doc should be first.
            # Heuristic: "Lead" in name? or just Alphabetical?
            # Config: Let's use Alphabetical for now as predictable default.
            jobs.sort(key=lambda x: x['name'])
            
            paths = [j['path'] for j in jobs]
            lead_name = jobs[0]['name']
            # Remove extension, add _PACKET
            out_name = lead_name.replace(".pdf", "") + f"_PACKET_{len(jobs)}Files.pdf"
            
            # Merge
            success, final_path = self.merge_files(paths, out_name)
            
            if success:
                # 4. Success: Register Packet
                new_status = "VERIFIED" # Packet is ready
                # Source becomes "Packet: EnvID"
                new_source = f"Packet: {env_id}"
                
                # Create Job
                # Calculate Hash (Optional, PyMuPDF save might change hash?)
                # We skip hash for speed on packet creation or calc it.
                # Let's verify Packet validity? 
                
                job_manager.create_job(
                    filename=os.path.basename(final_path),
                    file_path=final_path,
                    source=new_source,
                    initial_status=new_status
                )
                
                # 5. Mark Children COMPLETE
                for j in jobs:
                    job_manager.update_job_status(j['id'], 'MERGE_COMPLETE')
                    
                print(f"[PacketBuilder] Success: {out_name}")
            else:
                print(f"[PacketBuilder] Failed: {final_path}")
                # Mark children QA_FAILED? Or keep trying?
                # Mark QA_FAILED to alert Admin.
                for j in jobs:
                    job_manager.update_job_status(j['id'], 'QA_FAILED')

    def _get_conn(self):
         # Shim if job_manager doesn't expose conn (it locks)
         # We should use job_manager methods if possible.
         # For Step 1 (Fetch), we did it manually. 
         pass # Handled inline above
