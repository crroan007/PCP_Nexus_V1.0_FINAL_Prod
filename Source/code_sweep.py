"""Code sweep: look for potential bugs in the download/merge/verification pipeline."""
import os

source = 'D:/Homebrew Apps/PCP V1.0 (final) - Copy/PCP_USB_Backup_v1.0/Source'

files_to_check = [
    os.path.join(source, 'agents', 'hunter_v2.py'),
    os.path.join(source, 'core', 'verification_reporter.py'),
    os.path.join(source, 'utils', 'link_downloader.py'),
]

out_path = 'D:/Homebrew Apps/PCP V1.0 (final) - Copy/code_sweep.txt'

with open(out_path, 'w', encoding='utf-8') as out:
    for fpath in files_to_check:
        basename = os.path.basename(fpath)
        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        
        out.write(f"\n{'='*60}\n{basename}: {len(lines)} total lines\n{'='*60}\n")
        
        # 1. Find all except blocks
        out.write(f"\n--- except blocks ---\n")
        for i, line in enumerate(lines):
            if 'except ' in line or 'except:' in line:
                out.write(f"  L{i+1}: {line.rstrip()}\n")
        
        # 2. Find MultiDocumentResult usage
        out.write(f"\n--- MultiDocumentResult references ---\n")
        for i, line in enumerate(lines):
            if 'MultiDocumentResult' in line:
                out.write(f"  L{i+1}: {line.rstrip()}\n")
        
        # 3. Find LinkExpiredError usage
        out.write(f"\n--- LinkExpiredError references ---\n")
        for i, line in enumerate(lines):
            if 'LinkExpiredError' in line:
                out.write(f"  L{i+1}: {line.rstrip()}\n")
        
        # 4. Find download_file calls
        out.write(f"\n--- download_file calls ---\n")
        for i, line in enumerate(lines):
            if 'download_file(' in line or 'download_file (' in line:
                out.write(f"  L{i+1}: {line.rstrip()}\n")
        
        # 5. Find PdfReader usage (for page counting bugs)
        out.write(f"\n--- PdfReader usage ---\n")
        for i, line in enumerate(lines):
            if 'PdfReader' in line:
                out.write(f"  L{i+1}: {line.rstrip()}\n")
        
        # 6. Find os.remove / file cleanup
        out.write(f"\n--- file cleanup (os.remove/unlink) ---\n")
        for i, line in enumerate(lines):
            if 'os.remove(' in line or 'os.unlink(' in line or 'shutil.rmtree' in line:
                out.write(f"  L{i+1}: {line.rstrip()}\n")
        
        # 7. Find merge_pdf references
        out.write(f"\n--- merge/merge_pdf references ---\n")
        for i, line in enumerate(lines):
            if 'merge' in line.lower() and ('pdf' in line.lower() or 'files' in line.lower()):
                out.write(f"  L{i+1}: {line.rstrip()}\n")
        
        # 8. Find CL discard references
        out.write(f"\n--- CL/discard references ---\n")
        for i, line in enumerate(lines):
            if '_is_clerk_letter' in line or 'CL' in line or 'discard' in line.lower():
                out.write(f"  L{i+1}: {line.rstrip()}\n")

print(f"Done — {out_path}")
