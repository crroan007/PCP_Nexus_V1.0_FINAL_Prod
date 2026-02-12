"""Strip all PCP categories from Outlook Inbox emails so they get reprocessed."""
import pythoncom
import win32com.client

pythoncom.CoInitialize()
outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
inbox = outlook.GetDefaultFolder(6)  # 6 = Inbox
items = inbox.Items

count = 0
stripped = 0
for i in range(items.Count, 0, -1):
    msg = items.Item(i)
    try:
        cats = msg.Categories or ""
        if "PCP" in cats:
            msg.Categories = ""
            msg.Save()
            stripped += 1
        count += 1
    except Exception as e:
        pass

print(f"Scanned {count} emails, stripped categories from {stripped}")
pythoncom.CoUninitialize()
