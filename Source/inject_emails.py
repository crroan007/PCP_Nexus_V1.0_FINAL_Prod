"""
PCP Nexus - Email Injection Tool
=================================
Inject .eml test files into Outlook Inbox for testing.
Works by reading .eml content and creating new mail items.

Usage:
    python inject_emails.py

Requirements:
    - Outlook must be installed and configured
    - .eml test files in source directory
    - pywin32 package installed
"""

import os
import email
from email import policy
import win32com.client
import pythoncom


def inject_emails(source_dir: str, target_folder: str = "Inbox", account_hint: str = ""):
    """
    Inject all .eml files from source_dir into Outlook folder.
    
    Args:
        source_dir: Path to folder containing .eml files
        target_folder: Outlook folder name (default: Inbox)
        account_hint: Partial email/account name to match
    """
    pythoncom.CoInitialize()
    
    print(f"=" * 60)
    print(f"PCP NEXUS - EMAIL INJECTION TOOL")
    print(f"=" * 60)
    print(f"Source Directory: {source_dir}")
    print(f"Target Folder: {target_folder}")
    print(f"Account Hint: {account_hint or '(first account)'}")
    print(f"-" * 60)
    
    if not os.path.exists(source_dir):
        print(f"ERROR: Source directory not found: {source_dir}")
        return
    
    outlook = win32com.client.Dispatch("Outlook.Application")
    namespace = outlook.GetNamespace("MAPI")
    
    # Find account
    root = None
    for acc in namespace.Folders:
        if account_hint.lower() in acc.Name.lower() or not account_hint:
            root = acc
            print(f"Using Account: {acc.Name}")
            break
    
    if not root:
        print(f"ERROR: Account not found")
        print(f"Available accounts:")
        for acc in namespace.Folders:
            print(f"  - {acc.Name}")
        return
    
    # Get target folder
    try:
        folder = root.Folders(target_folder)
        print(f"Target Folder: {folder.Name}")
        print(f"Current email count: {folder.Items.Count}")
    except Exception as e:
        print(f"ERROR: Cannot access folder '{target_folder}': {e}")
        print(f"Available folders:")
        for f in root.Folders:
            print(f"  - {f.Name}")
        return
    
    print(f"-" * 60)
    print(f"Scanning for .eml files...")
    
    injected = 0
    errors = 0
    
    # Walk all subdirectories
    for dirpath, dirs, files in os.walk(source_dir):
        for filename in files:
            if not filename.lower().endswith('.eml'):
                continue
            
            filepath = os.path.join(dirpath, filename)
            try:
                # Parse .eml file
                with open(filepath, 'rb') as f:
                    msg = email.message_from_binary_file(f, policy=policy.default)
                
                # Create Outlook mail item
                mail = outlook.CreateItem(0)  # 0 = MailItem
                mail.Subject = msg.get('Subject', 'No Subject')
                
                # Extract body (prefer HTML)
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ct = part.get_content_type()
                        if ct == 'text/html':
                            body = part.get_content()
                            mail.HTMLBody = body
                            break
                        elif ct == 'text/plain' and not body:
                            body = part.get_content()
                else:
                    body = msg.get_content()
                
                if not mail.HTMLBody and body:
                    mail.Body = body
                
                # Set as unread
                mail.UnRead = True
                
                # Save and move to target folder
                mail.Save()
                mail.Move(folder)
                
                injected += 1
                print(f"  ✓ [{injected:3d}] {filename[:50]}")
                
                if injected % 20 == 0:
                    print(f"  ...{injected} emails injected so far...")
                    
            except Exception as e:
                errors += 1
                if errors <= 5:  # Only show first 5 errors
                    print(f"  ✗ [ERR] {filename[:40]}: {e}")
                elif errors == 6:
                    print(f"  ... (suppressing further error messages)")
    
    print(f"=" * 60)
    print(f"INJECTION COMPLETE")
    print(f"=" * 60)
    print(f"Successfully injected: {injected}")
    print(f"Errors: {errors}")
    print(f"Folder now has: {folder.Items.Count} total emails")
    print(f"=" * 60)


if __name__ == "__main__":
    # =======================================================================
    # CONFIGURATION - Modify these settings as needed
    # =======================================================================
    
    # OPTION 1: Phase 1 Testing (Civil Affidavits)
    SOURCE_DIR = r"Phase1_Examples_Fresh"
    
    # OPTION 2: Phase 2 Testing (Criminal e-Filings)
    # SOURCE_DIR = r"Phase2_Examples_Fresh"
    
    # Target Outlook folder
    TARGET_FOLDER = "Inbox"
    
    # Account hint (leave empty to use first account)
    ACCOUNT_HINT = ""
    
    # =======================================================================
    # RUN INJECTION
    # =======================================================================
    
    print("")
    print("Starting email injection...")
    print(f"Ensure Outlook is running and configured.")
    print("")
    
    try:
        inject_emails(
            source_dir=SOURCE_DIR,
            target_folder=TARGET_FOLDER,
            account_hint=ACCOUNT_HINT
        )
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    print("\nDone! Close this window or press Ctrl+C to exit.")
    input("Press Enter to continue...")
