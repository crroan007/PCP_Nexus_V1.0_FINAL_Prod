
$ErrorActionPreference = "Stop"
try {
    Invoke-WebRequest -Uri "https://texas.tylertech.cloud/ViewDocuments.aspx?FID=bb5bd745-cbb5-46ea-b512-19a74c1d927a" -OutFile "C:\Homebrew Apps\PCP New\PCP_Delivery_Package\Source\Executive\Orchestrator\Staging\P2_109426446_114508_097227_DL_AXPM.pdf" -UserAgent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" -TimeoutSec 20
    exit 0
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
