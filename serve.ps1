# Minimal static file server — no Python or Node required.
#   .\serve.ps1            → http://localhost:8845
#   .\serve.ps1 -Port 9000
param([int]$Port = 8845)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

$mime = @{
  '.html' = 'text/html; charset=utf-8'
  '.css'  = 'text/css; charset=utf-8'
  '.js'   = 'application/javascript; charset=utf-8'
  '.json' = 'application/json; charset=utf-8'
  '.jsonl'= 'application/x-ndjson; charset=utf-8'
  '.svg'  = 'image/svg+xml'
  '.png'  = 'image/png'
  '.jpg'  = 'image/jpeg'
  '.ico'  = 'image/x-icon'
  '.md'   = 'text/markdown; charset=utf-8'
}

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:$Port/")
try {
  $listener.Start()
} catch {
  Write-Host "Could not bind port $Port. Try: .\serve.ps1 -Port 9000" -ForegroundColor Red
  exit 1
}

Write-Host "Serving $root" -ForegroundColor Cyan
Write-Host "  http://localhost:$Port/" -ForegroundColor Green
Write-Host "Ctrl+C to stop." -ForegroundColor DarkGray

try {
  while ($listener.IsListening) {
    $ctx = $listener.GetContext()
    $req = $ctx.Request
    $res = $ctx.Response
    try {
      $rel = [Uri]::UnescapeDataString($req.Url.AbsolutePath).TrimStart('/')
      if ($rel -eq '') { $rel = 'index.html' }

      $full = Join-Path $root $rel
      # Block traversal outside the served root
      $resolved = [System.IO.Path]::GetFullPath($full)
      if (-not $resolved.StartsWith([System.IO.Path]::GetFullPath($root))) {
        $res.StatusCode = 403
        $res.Close(); continue
      }

      if (Test-Path $resolved -PathType Leaf) {
        $ext = [System.IO.Path]::GetExtension($resolved).ToLower()
        $res.ContentType = if ($mime.ContainsKey($ext)) { $mime[$ext] } else { 'application/octet-stream' }
        $res.Headers.Add('Cache-Control', 'no-store')
        $bytes = [System.IO.File]::ReadAllBytes($resolved)
        $res.ContentLength64 = $bytes.Length
        $res.OutputStream.Write($bytes, 0, $bytes.Length)
        Write-Host ("  200  " + $rel) -ForegroundColor DarkGray
      } else {
        $res.StatusCode = 404
        $msg = [System.Text.Encoding]::UTF8.GetBytes("404 Not Found: $rel")
        $res.OutputStream.Write($msg, 0, $msg.Length)
        Write-Host ("  404  " + $rel) -ForegroundColor DarkYellow
      }
    } catch {
      $res.StatusCode = 500
    } finally {
      $res.Close()
    }
  }
} finally {
  $listener.Stop()
  $listener.Dispose()
}
