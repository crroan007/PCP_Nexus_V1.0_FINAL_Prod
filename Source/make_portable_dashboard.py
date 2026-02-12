"""
Create a portable dashboard with LIVE PDF links pointing to outputs/ folder.
Also copies any referenced PDFs that are missing from the repo's outputs/.
"""
import re
import os
import base64
import shutil

DASHBOARD_SRC = "C:/ProgramData/PCP-Automation/Dashboard/dashboard.html"
LOGO_SRC = "C:/ProgramData/PCP-Automation/Dashboard/assets/pcp_logo.jpg"
REPO_DIR = "D:/Homebrew Apps/PCP V1.0 (final) - Copy/PCP_GitHub_Repo"
OUTPUT_FILE = os.path.join(REPO_DIR, "index.html")
REPO_OUTPUTS = os.path.join(REPO_DIR, "outputs")

# Map of file:/// base paths to local directories
PATH_MAP = {
    "file:///C:/Users/Kado/Documents/PCP_Output/Criminal/": "C:/Users/Kado/Documents/PCP_Output/Criminal/",
    "file:///C:/Users/Kado/Documents/PCP_Output/Civil/": "C:/Users/Kado/Documents/PCP_Output/Civil/",
    "file:///C:/ProgramData/PCP-Automation/Staging/": "C:/ProgramData/PCP-Automation/Staging/",
}

print("=" * 60)
print("  PCP Nexus — Portable Dashboard with Live PDF Links")
print("=" * 60)

# Read source
with open(DASHBOARD_SRC, "r", encoding="utf-8") as f:
    html = f.read()

print(f"  Source: {len(html):,} bytes")

# 1. Base64-embed the logo
if os.path.exists(LOGO_SRC):
    with open(LOGO_SRC, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode("ascii")
    html = html.replace(
        'src="assets/pcp_logo.jpg"',
        f'src="data:image/jpeg;base64,{logo_b64}"'
    )
    print("  ✅ Logo embedded as base64")

# 2. Find all referenced files and copy missing ones to outputs/
os.makedirs(REPO_OUTPUTS, exist_ok=True)
existing_outputs = set(os.listdir(REPO_OUTPUTS))
print(f"  Existing outputs in repo: {len(existing_outputs)}")

# Extract all file:/// links
file_links = re.findall(r"file:///[^\"'<>\s]+", html)
copied = 0
missing = 0
already_there = 0

for link in set(file_links):
    # Get just the filename
    filename = link.rsplit("/", 1)[-1]
    
    if filename in existing_outputs:
        already_there += 1
        continue
    
    # Try to find the source file
    found = False
    for url_prefix, local_dir in PATH_MAP.items():
        if link.startswith(url_prefix):
            local_path = os.path.join(local_dir, filename)
            if os.path.exists(local_path):
                shutil.copy2(local_path, os.path.join(REPO_OUTPUTS, filename))
                copied += 1
                found = True
            break
    
    if not found:
        # Try all directories as fallback
        for url_prefix, local_dir in PATH_MAP.items():
            local_path = os.path.join(local_dir, filename)
            if os.path.exists(local_path):
                shutil.copy2(local_path, os.path.join(REPO_OUTPUTS, filename))
                copied += 1
                found = True
                break
    
    if not found:
        missing += 1
        print(f"    ⚠️  Missing: {filename}")

print(f"  ✅ PDFs already in repo: {already_there}")
print(f"  ✅ PDFs copied to outputs/: {copied}")
if missing:
    print(f"  ⚠️  PDFs not found locally: {missing}")

# 3. Rewrite file:/// links to relative outputs/ paths
def rewrite_link(match):
    full_match = match.group(0)
    url = match.group(1) or match.group(2)  # single or double quote
    filename = url.rsplit("/", 1)[-1]
    quote = "'" if match.group(1) else '"'
    # Replace URL, keep everything else
    return full_match.replace(url, f"outputs/{filename}")

# Handle single-quote hrefs
html = re.sub(
    r"href='(file:///[^']*)'",
    lambda m: f"href='outputs/{m.group(1).rsplit('/', 1)[-1]}'",
    html
)

# Handle double-quote hrefs  
html = re.sub(
    r'href="(file:///[^"]*)"',
    lambda m: f'href="outputs/{m.group(1).rsplit("/", 1)[-1]}"',
    html
)

remaining = len(re.findall(r"file:///", html))
print(f"  ✅ Links rewritten to outputs/ relative paths")
if remaining:
    print(f"    ℹ️  {remaining} remaining file:/// references (non-href, e.g. in JS)")

# 4. Disable auto-refresh
html = html.replace(
    '<input type="checkbox" id="refreshToggle" checked>',
    '<input type="checkbox" id="refreshToggle">'
)
print("  ✅ Auto-refresh disabled")

# 5. Update engine banner
html = re.sub(
    r'<div class="engine-banner[^"]*">[^<]*</div>',
    '<div class="engine-banner idle">📸 Static Snapshot &mdash; Test results from 2026-02-11 (247 jobs processed)</div>',
    html,
    count=1
)

# 6. Add portable banner
portable_banner = '''
    <!-- PORTABLE SNAPSHOT BANNER -->
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0c4a6e 100%); 
                border: 1px solid #38bdf8; border-radius: 8px; padding: 12px 20px; 
                margin-bottom: 16px; display: flex; align-items: center; gap: 12px;
                font-size: 0.85rem; color: #93c5fd;">
        <span style="font-size: 1.2rem;">📋</span>
        <div>
            <strong style="color: #38bdf8;">PCP Nexus — Production Test Results</strong><br>
            <span style="color: #94a3b8; font-size: 0.8rem;">
                Generated: 2026-02-11 20:10 EST &bull; 247 jobs processed &bull; 100% success rate &bull;
                Click any filename to open the output PDF
            </span>
        </div>
    </div>
'''
html = html.replace(
    '<!-- ENGINE STATUS BANNER -->',
    '<!-- ENGINE STATUS BANNER -->\n' + portable_banner
)

# 7. Write output
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(html)

# Summary
total_outputs = len(os.listdir(REPO_OUTPUTS))
total_size_mb = sum(os.path.getsize(os.path.join(REPO_OUTPUTS, f)) for f in os.listdir(REPO_OUTPUTS)) / (1024*1024)
print(f"\n  📁 Dashboard: {OUTPUT_FILE}")
print(f"  📁 Outputs folder: {total_outputs} files, {total_size_mb:.0f} MB")
print(f"\n  Ready to git add, commit, and push!")
print("=" * 60)
