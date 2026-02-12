import win32com.client
import pythoncom

def check_inbox_categories():
    pythoncom.CoInitialize()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
        
        # Determine target folder
        # We'll check the default Inbox first
        inbox = namespace.GetDefaultFolder(6)
        
        print(f"Checking Folder: {inbox.Name} (Count: {inbox.Items.Count})")
        
        items = inbox.Items
        items.Sort("[ReceivedTime]", True)
        
        for i in range(1, min(20, items.Count) + 1):
            m = items.Item(i)
            print(f"#{i} | Subj: {m.Subject[:50]} | Cats: {m.Categories or 'NONE'}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        pythoncom.CoInitialize()

if __name__ == "__main__":
    check_inbox_categories()
