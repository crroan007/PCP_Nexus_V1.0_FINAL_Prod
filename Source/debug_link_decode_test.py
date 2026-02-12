from utils.link_downloader import LinkDownloader
import logging

# Setup basic logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Debug")
dl = LinkDownloader(logger)

# Link from Analysis Report
TEST_LINK = "https://urldefense.proofpoint.com/v2/url?u=https-3A__texas.tylertech.cloud_ViewDocuments.aspx-3FFID-3De0a4632b-2D2f33-2D4c29-2D9e8d-2Dd1d4b6a8a0b0&d=DwMGaQ&c=euGZstcaTDllvimEN8b7jXrwqOf-v5A_CdpgnVfiiMM&r=J5Ujdbd8f8Xj4q_i5h_k7A&m=...&s=..."

print(f"Original: {TEST_LINK}")

# 1. Test Decode
decoded = dl.decode_proofpoint_url(TEST_LINK)
print(f"Decoded: {decoded}")

# 2. Test Fetch (HEAD request only to check status)
try:
    import requests
    print(f"Attempting HEAD request to: {decoded}")
    # Use headers from downloader
    h = dl.headers
    r = requests.head(decoded, headers=h, timeout=10, allow_redirects=True)
    print(f"Status Code: {r.status_code}")
    print(f"Content-Type: {r.headers.get('Content-Type')}")
    print(f"Final URL: {r.url}")
except Exception as e:
    print(f"Request verification failed: {e}")
