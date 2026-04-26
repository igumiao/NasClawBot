param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$python = [System.IO.Path]::GetFullPath($python)

if (-not (Test-Path $python)) {
    throw "Project virtual environment not found at $python. Create it first with `C:\Users\10762\anaconda3\envs\python311\python.exe -m venv .venv`."
}

& $python @Args
exit $LASTEXITCODE
