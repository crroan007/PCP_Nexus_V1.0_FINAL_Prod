import win32com.client
import pythoncom
import time

def reset_categories():
    pythoncom.CoInitialize()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
        inbox = namespace.GetDefaultFolder(6)
        
        print(f"Scanning {inbox.Name} for tags to reset...")
        items = inbox.Items
        count = 0
        
        # We scan the last 100 items for efficiency
        items.Sort("[ReceivedTime]", True)
        
        for i in range(1, min(100, items.Count) + 1):
            m = items.Item(i)
            cats = m.Categories or ""
            if "PCP-Processed" in cats or "PCP-Packetized" in cats:
                # Remove the tags
                new_cats = cats.replace("PCP-Processed", "").replace("PCP-Packetized", "").strip("; ")
                m.Categories = new_cats
                m.Save()
                print(f"Reset: {m.Subject[:50]}")
                count += 1
        
        print(f"Finished. Reset {count} emails.")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        pythoncom.CoUninitialize()

if __name__ == "__main__":
    reset_categories()
