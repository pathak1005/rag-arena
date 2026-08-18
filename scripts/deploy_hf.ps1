# Deploy to Hugging Face Spaces.
#
# Prerequisite (run once, interactively - it stores a token in your user profile):
#     .\.venv\Scripts\hf.exe auth login
#
# Then:
#     .\scripts\deploy_hf.ps1 -User <your-hf-username>

param(
    [Parameter(Mandatory=$true)][string]$User,
    [string]$Space = "rag-arena",
    [string]$WorkDir = "$env:TEMP\hf-rag-arena"
)

$ErrorActionPreference = "Stop"
$repo = "$User/$Space"
$hf = ".\.venv\Scripts\hf.exe"

Write-Host "== Checking authentication ==" -ForegroundColor Cyan
& $hf auth whoami
if ($LASTEXITCODE -ne 0) {
    Write-Host "Not logged in. Run: $hf auth login" -ForegroundColor Red
    exit 1
}

Write-Host "== Creating Space $repo (ok if it already exists) ==" -ForegroundColor Cyan
& $hf repo create $Space --repo-type space --space_sdk docker -y 2>&1 | Out-Host

Write-Host "== Preparing working copy at $WorkDir ==" -ForegroundColor Cyan
if (Test-Path $WorkDir) { Remove-Item -Recurse -Force $WorkDir }
git clone "https://huggingface.co/spaces/$repo" $WorkDir 2>&1 | Out-Host

# Copy the project in, excluding local-only artefacts. The Space README must carry the
# HF frontmatter, so it replaces the GitHub README.
$exclude = @('.git', '.venv', '__pycache__', '.pytest_cache', 'data\chroma',
             'data\briefs', 'data\admin_credentials.json', 'hf-space')
Get-ChildItem -Path . -Force | Where-Object {
    $name = $_.Name
    -not ($exclude | Where-Object { $name -eq $_ -or $name -like "$_*" })
} | ForEach-Object {
    Copy-Item $_.FullName -Destination $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
}

Copy-Item ".\deploy\huggingface\README.md" -Destination "$WorkDir\README.md" -Force
Remove-Item "$WorkDir\data\admin_credentials.json" -Force -ErrorAction SilentlyContinue
Remove-Item "$WorkDir\.venv" -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "== Pushing ==" -ForegroundColor Cyan
Push-Location $WorkDir
git add -A
git -c user.email="deploy@local" -c user.name="deploy" commit -m "Deploy RAG Arena" 2>&1 | Out-Host
git push 2>&1 | Out-Host
Pop-Location

Write-Host ""
Write-Host "Space: https://huggingface.co/spaces/$repo" -ForegroundColor Green
Write-Host "App:   https://$($User.Replace('_','-'))-$Space.hf.space" -ForegroundColor Green
Write-Host ""
Write-Host "NEXT, in the Space Settings > Variables and secrets:" -ForegroundColor Yellow
Write-Host "  GROQ_API_KEY = <your key>        (Secret)"
Write-Host "  ADMIN_EMAIL  = <your email>      (Secret)"
Write-Host "  ADMIN_SLUG   = <something private> (Secret)"
Write-Host ""
Write-Host "Then register the admin account immediately at ?admin=<ADMIN_SLUG>" -ForegroundColor Yellow
