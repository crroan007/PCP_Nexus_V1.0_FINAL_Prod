"""
Inject .msg files into Outlook Inbox (Deleted Items for Phase 1, Inbox for Phase 2).
Uses OpenSharedItem which works natively with .msg files.
"""
import os
import sys
import win32com.client
import pythoncom
import time

def inject_msg_files(source_dir, target_folder_name, account_hint="lunarius"):
    pythoncom.CoInitialize()
    outlook = win32com.client.Dispatch("Outlook.Application")
    namespace = outlook.GetNamespace("MAPI")
    
    # Find account
    root = None
    for acc in namespace.Folders:
        if account_hint.lower() in acc.Name.lower():
            root = acc
            break
    
    if not root:
        print(f"ERROR: Account matching '{account_hint}' not found")
        return 0
    
    # Navigate to target folder
    try:
        parts = target_folder_name.split("\\")
        folder = root
        for part in parts:
            if part and part.lower() != root.Name.lower():
                folder = folder.Folders(part)
    except Exception as e:
        print(f"ERROR: Could not find folder '{target_folder_name}': {e}")
        return 0
    
    print(f"Target: {root.Name}\\{target_folder_name}")
    
    # Collect all .msg files
    msg_files = []
    for dirpath, _, files in os.walk(source_dir):
        for f in files:
            if f.lower().endswith('.msg'):
                msg_files.append(os.path.join(dirpath, f))
    
    print(f"Found {len(msg_files)} .msg files to inject")
    
    injected = 0
    errors = 0
    for i, filepath in enumerate(msg_files):
        try:
            msg = namespace.OpenSharedItem(filepath)
            msg.UnRead = True
            msg.Move(folder)
            injected += 1
            if (i + 1) % 10 == 0:
                print(f"  [{i+1}/{len(msg_files)}] injected...")
        except Exception as e:
            print(f"  [ERR] {os.path.basename(filepath)}: {e}")
            errors += 1
    
    print(f"Done: {injected} injected, {errors} errors")
    return injected


if __name__ == "__main__":
    base = r"D:\Homebrew Apps\PCP V1.0 (final) - Copy\Test Emails"
    
    p1_dir = os.path.join(base, "Phase 1")
    p2_dir = os.path.join(base, "Phase 2")
    
    p1_count = len([f for f in os.listdir(p1_dir) if f.lower().endswith('.msg')]) if os.path.isdir(p1_dir) else 0
    p2_count = len([f for f in os.listdir(p2_dir) if f.lower().endswith('.msg')]) if os.path.isdir(p2_dir) else 0
    
    print(f"Phase 1: {p1_count} msgs -> Deleted Items")
    print(f"Phase 2: {p2_count} msgs -> Inbox")
    print()
    
    if p1_count > 0:
        print("=== Injecting Phase 1 ===")
        inject_msg_files(p1_dir, "Deleted Items", "lunarius")
        print()
    
    if p2_count > 0:
        print("=== Injecting Phase 2 ===")
        inject_msg_files(p2_dir, "Inbox", "lunarius")
