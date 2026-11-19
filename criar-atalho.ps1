# Cria o atalho "AutoCOR" na área de trabalho, com o ícone do Grupo Protege.
# Uso: clique com o botão direito > Executar com o PowerShell (ou: powershell -ExecutionPolicy Bypass -File criar-atalho.ps1)
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $repo ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { Write-Error "Não achei $pythonw (crie o .venv antes)."; exit 1 }
$destino = Join-Path ([Environment]::GetFolderPath("Desktop")) "AutoCOR.lnk"
$sh = New-Object -ComObject WScript.Shell
$lnk = $sh.CreateShortcut($destino)
$lnk.TargetPath = $pythonw
$lnk.Arguments = '"' + (Join-Path $repo "abrir-app.pyw") + '"'
$lnk.WorkingDirectory = $repo
$lnk.IconLocation = (Join-Path $repo "src\sgcor_renov\ui\recursos\icone.ico") + ",0"
$lnk.Description = "AutoCOR — renovações lotéricas → SGCOR (Grupo Protege)"
$lnk.Save()
Write-Output "Atalho criado: $destino"
