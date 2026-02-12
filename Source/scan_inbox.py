"""Scan Outlook inbox and classify emails by type to understand the distribution."""
import pythoncom
import win32com.client

pythoncom.CoInitialize()
outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
inbox = outlook.GetDefaultFolder(6)
items = inbox.Items

total = items.Count
print(f"Total inbox emails: {total}")

filing_accepted = 0
other_subjects = {}
with_pcp_cat = 0
no_cat = 0
phase1_candidates = 0  # Filing Accepted WITHOUT Tyler prefixes
phase2_candidates = 0  # Filing Accepted WITH Tyler prefixes (AX40/AXPB/AXPE in body or subject)

sample_subjects = []

for i in range(1, min(total + 1, total + 1)):  # scan all
    try:
        msg = items.Item(i)
        subject = msg.Subject or ""
        cats = msg.Categories or ""
        body = (msg.Body or "")[:500]
        
        if "PCP" in cats:
            with_pcp_cat += 1
        else:
            no_cat += 1
        
        if "Filing Accepted" in subject:
            filing_accepted += 1
            # Check if Phase 2 (has Tyler prefixes in body)
            has_prefix = any(p in body for p in ["AX40", "AXPB", "AXPE"])
            if has_prefix:
                phase2_candidates += 1
            else:
                phase1_candidates += 1
        else:
            # Bucket by first 30 chars of subject
            key = subject[:40] if subject else "(no subject)"
            other_subjects[key] = other_subjects.get(key, 0) + 1
            if len(sample_subjects) < 5:
                sample_subjects.append(subject[:80])
    except Exception as e:
        pass

print(f"\n=== CLASSIFICATION ===")
print(f"'Filing Accepted' emails: {filing_accepted}")
print(f"  -> Phase 1 candidates (no AX prefixes): {phase1_candidates}")
print(f"  -> Phase 2 candidates (AX prefixes): {phase2_candidates}")
print(f"Other subjects: {total - filing_accepted}")
print(f"Still have PCP categories: {with_pcp_cat}")
print(f"No PCP categories: {no_cat}")

print(f"\n=== TOP OTHER SUBJECT PATTERNS ===")
for subj, count in sorted(other_subjects.items(), key=lambda x: -x[1])[:15]:
    print(f"  {count:4d}x  {subj}")

print(f"\n=== SAMPLE NON-FILING SUBJECTS ===")
for s in sample_subjects:
    print(f"  {s}")

pythoncom.CoUninitialize()
