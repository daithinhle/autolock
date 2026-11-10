# Đóng gói AutoLock bằng PyInstaller.
#   dist\AutoLock\AutoLock.exe              bản chạy trên máy này (dữ liệu ở %LOCALAPPDATA%\AutoLock)
#   dist\AutoLock-portable-<ngày>.zip       bản mang sang máy khác (có thư mục data\ rỗng + HUONG-DAN.txt)
param([switch]$SkipTests)

# Lệnh native (PyInstaller, pip) ghi log ra stderr: không coi là lỗi, kiểm tra $LASTEXITCODE thay vào đó.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Tạo virtualenv..."
    python -m venv .venv
    & $py -m pip install -r requirements.txt
    if ($LASTEXITCODE) { throw "pip install lỗi" }
}

& $py tools\download_models.py
if ($LASTEXITCODE) { throw "Thiếu model" }

if (-not $SkipTests) {
    & $py -m pytest -q
    if ($LASTEXITCODE) { throw "Unit test lỗi" }
}

foreach ($d in "build\pyinstaller", "dist\AutoLock") {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}

& $py tools\make_icon.py build\autolock.ico | Out-Null

& $py -m PyInstaller --noconfirm --clean --windowed `
    --name AutoLock `
    --icon "$PSScriptRoot\build\autolock.ico" `
    --add-data "$PSScriptRoot\models;models" `
    --hidden-import pystray._win32 `
    --hidden-import PIL.ImageTk `
    --exclude-module pytest `
    --workpath build\pyinstaller `
    --specpath build `
    --distpath dist `
    main.py
if ($LASTEXITCODE) { throw "PyInstaller lỗi" }

# Bỏ file không dùng: backend ffmpeg của OpenCV (app đọc camera qua DirectShow) và codec AVIF của Pillow.
$trash = Get-ChildItem dist\AutoLock -Recurse -File |
    Where-Object { $_.Name -like "opencv_videoio_ffmpeg*.dll" -or $_.Name -like "*avif*" }
$saved = ($trash | Measure-Object Length -Sum).Sum
$trash | Remove-Item -Force
Write-Host ("Đã bỏ {0} file không dùng ({1:N1} MB)" -f $trash.Count, ($saved / 1MB))

# Bản local không được có thư mục data\ (dùng %LOCALAPPDATA%\AutoLock).
if (Test-Path dist\AutoLock\data) { Remove-Item -Recurse -Force dist\AutoLock\data }

# Gói portable: sạch, không chứa cấu hình/khuôn mặt/log/ảnh của máy build.
$stamp = Get-Date -Format "yyyyMMdd"
$stage = "build\portable\AutoLock"
if (Test-Path "build\portable") { Remove-Item -Recurse -Force "build\portable" }
New-Item -ItemType Directory -Force $stage | Out-Null
Copy-Item -Recurse dist\AutoLock\* $stage
New-Item -ItemType Directory -Force "$stage\data" | Out-Null
Copy-Item HUONG-DAN.txt $stage
$zip = "dist\AutoLock-portable-$stamp.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
# Nén bằng zipfile của Python (tên mục dùng "/", giải nén được ở mọi nơi). Thử lại nếu file đang bị trình quét virus giữ.
& $py -c @"
import shutil, sys, time
for i in range(5):
    try:
        shutil.make_archive(sys.argv[1][:-4], 'zip', root_dir='build/portable', base_dir='AutoLock')
        break
    except OSError as e:
        if i == 4: raise
        print('Nén lỗi (%s), thử lại...' % e); time.sleep(3)
"@ $zip
if ($LASTEXITCODE) { throw "Không tạo được $zip" }
$exeSize = (Get-ChildItem dist\AutoLock -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("dist\AutoLock: {0:N0} MB" -f ($exeSize / 1MB))
Write-Host ("{0}: {1:N0} MB" -f $zip, ((Get-Item $zip).Length / 1MB))
