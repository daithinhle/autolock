# AutoLock

Tự khóa Windows khi bạn (chủ máy) rời khỏi webcam. Chạy ẩn ở khay hệ thống, xử lý 100% local, không gửi gì ra ngoài. Không lưu ảnh của bạn; chỉ lưu ảnh người lạ (có thể tắt).

## Lần đầu sử dụng

Mở `AutoLock.exe`: cửa sổ **Đăng ký khuôn mặt chủ máy** hiện ra (đây là cửa sổ duy nhất có hình camera).
Bấm "Bắt đầu quét" rồi làm theo 6 bước: nhìn thẳng, quay trái, quay phải, ngẩng, cúi, nhìn thẳng.
Bước đầu ghi lại tư thế gốc của bạn, các bước sau so với tư thế đó. Nếu một bước không nhận được tư thế, sau 5s nó tự chấp nhận.
App chỉ lưu 24 vector đặc trưng vào `%LOCALAPPDATA%\AutoLock\owner.npz`. Đăng ký lại bằng menu tray.

## Cách hoạt động

Mỗi 0.5s chụp 1 frame và coi là **có mặt** nếu:
1. Thấy **mặt chủ máy** (YuNet + SFace, độ giống ≥ 0.40), hoặc
2. Không thấy mặt / mặt không rõ ai (góc nghiêng, thiếu sáng) nhưng thấy người đủ lớn trong khung hình (YOLOX), hoặc có gõ phím/di chuột trong 5s gần nhất.

Nếu chỉ thấy **mặt người lạ** (độ giống < 0.25) thì coi như chủ máy đã rời đi: dù người đó có gõ phím, máy vẫn khóa sau 12s.
Để không nhận nhầm chủ máy là người lạ, kết luận "người lạ" cần bằng chứng rõ:
- mọi khuôn mặt trong hình đều đủ rõ để đánh giá: rộng ≥ 64px, độ tin cậy phát hiện ≥ 0.8, gần chính diện, không nhòe, không bị cắt ở mép khung hình;
- thấy người lạ ở 2 lần kiểm tra liên tiếp (cách nhau ≤ 3s). Lần đầu nghi ngờ thì lần kiểm tra kế tiếp chạy ngay, kể cả khi đang gõ phím.

Mặt không đạt các điều kiện trên được tính là "không rõ ai" (dùng phát hiện người / bàn phím).
Phòng tối: ảnh được tự tăng sáng trước khi tìm khuôn mặt.

Vắng 3s thì icon chuyển vàng, còn 5s thì báo trước, vắng 12s (chỉnh được) thì khóa máy. Khi máy khóa (kể cả Win+L), camera tắt và bật lại sau khi bạn mở khóa.
Frame đọc lỗi không bao giờ bị tính là vắng mặt.

**Tự khóa khi không thao tác** (mặc định tắt): khóa sau N phút không gõ phím/di chuột, dù camera vẫn thấy bạn; báo trước 15s. Vẫn hoạt động khi không có camera.
Chỉnh nhanh ở menu tray → "Tự khóa khi không thao tác", hoặc trong "Cài đặt...".

**Lịch hoạt động** (mặc định tắt): chỉ theo dõi và tự khóa vào các ngày trong tuần đã chọn (mặc định T2–T6) và trong khung giờ
(mặc định 00:00–24:00 = cả ngày; giờ kết thúc nhỏ hơn giờ bắt đầu = qua đêm, tính cho ngày bắt đầu). Ngoài lịch: camera tắt,
không khóa (kể cả tự khóa khi không thao tác), icon xám. Chỉnh trong "Cài đặt..." → "Lịch hoạt động"; bật/tắt nhanh ở menu tray.

## Tự học góc mặt chủ máy

Để không nhận nhầm bạn là người lạ khi quay đầu, cúi xuống hay đổi ánh sáng:
- **Bám theo khuôn mặt**: sau một lần nhận ra chắc chắn (độ giống ≥ 0.5), cùng khuôn mặt đó (chỉ 1 người trong hình,
  khung mặt chồng lên vị trí cũ, cách nhau ≤ 2s, hoặc ≤ 5s khi bàn phím/chuột vẫn được dùng) vẫn là chủ máy dù điểm tụt.
  Người khác không thể "nối" vào chuỗi này vì chủ máy phải rời đi, chuỗi bị đứt. Hai khuôn mặt trong hình thì không bám.
- **Học mẫu mới**: chỉ những frame đang được bám theo và có điểm < 0.55 (góc hồ sơ chưa có), qua cổng chất lượng
  (mặt ≥ 80px, độ tin cậy phát hiện ≥ 0.9, không nhòe). Tối đa 1 mẫu/20s, 30 mẫu/ngày, 150 mẫu (bỏ mẫu cũ nhất).
  24 mẫu đăng ký ban đầu không bao giờ bị thay; đăng ký lại sẽ xóa mẫu tự học.
- Cài đặt → "Khuôn mặt chủ máy": bật/tắt, xem số mẫu, "Xóa mẫu tự học".

- **Chống trôi**: mẫu học được luôn phải còn đủ gần bộ đăng ký gốc (≥ 0.30), nên thư viện không "bò" dần sang mặt người khác.
- **Kiểm tra mẫu** (Cài đặt → "Khuôn mặt chủ máy" → "Kiểm tra mẫu..."): xem từng mẫu kèm % giống bộ gốc (xanh/vàng/đỏ),
  tích "xóa" để bỏ; nút "Quét lại & tự lọc" mở camera, bạn ngồi vài giây, app tự loại mẫu không còn khớp bạn.
- **Ảnh thu nhỏ** (mặc định tắt): bật thì mỗi mẫu kèm 1 ảnh mặt nhỏ (lưu `<data>/learned`) để xem bằng mắt. Đây là
  ngoại lệ duy nhất app lưu ảnh của bạn; tắt đi thì chỉ còn vector.

## Ảnh người lạ

Khi camera chỉ thấy người lạ (độ giống với chủ máy < 0.25), app chụp tối đa 3 ảnh mỗi lần xuất hiện, cách nhau ≥10s,
khoanh đỏ khuôn mặt và ghi thời gian. Ảnh lưu ở `%LOCALAPPDATA%\AutoLock\strangers\` và giữ 7 ngày (chỉnh 1–30 ngày, tối đa 500 ảnh).
Mặt không rõ ai (góc nghiêng, thiếu sáng) không bị chụp. Sau khi bạn mở khóa, có thông báo nếu có ảnh mới.
Xem nhanh: menu tray → "Ảnh người lạ (N)". Tắt/đổi thời hạn trong Cài đặt.

## Log

`%LOCALAPPDATA%\AutoLock\autolock.log`, xoay vòng mỗi giờ, **chỉ giữ 24 giờ gần nhất** (dọn cả khi khởi động và mỗi giờ).
Chỉ tiến trình chính ghi log; cửa sổ đăng ký/cài đặt không ghi để tránh tranh chấp file khi xoay vòng.

## Chế độ camera

| | Khi cần (mặc định trên laptop) | Liên tục (mặc định trên máy bàn) |
|---|---|---|
| Lúc bạn đang gõ phím/di chuột | Camera **tắt** | Camera bật, kiểm tra mỗi 3s |
| Ngừng thao tác X giây (mặc định 8, chỉnh 3–120) | Camera bật (~1–3s để sẵn sàng) | — |
| Người lạ ngồi vào gõ ngay | Bị phát hiện ở lần kiểm tra định kỳ (mỗi ~3 phút ±20%, chỉnh 0–60) | Trong ~3s |
| CPU khi đang làm việc (đo trên máy dev) | ~0.1% | ~2.1% |

Ở chế độ Khi cần, thời gian khóa vẫn tính từ lần thao tác cuối (không cộng thêm X giây),
nhưng luôn quan sát ít nhất 4s sau khi camera sẵn sàng trước khi khóa; camera giữ bật tối thiểu 5s để đèn không nhấp nháy.
Driver camera trên máy dev bỏ qua yêu cầu giảm FPS (vẫn 30fps), nên tắt hẳn camera là cách tiết kiệm duy nhất.

## Tài nguyên

- Độ ưu tiên tiến trình Below Normal + Efficiency mode (EcoQoS), OpenCV chạy 1 luồng.
- Đang gõ phím/di chuột: không giải mã/phân tích ảnh, chỉ kiểm tra người lạ mỗi 3s.
- Model phát hiện người (nặng nhất) chỉ chạy khi không thấy mặt chủ máy và không có thao tác.
- Chạy pin: 1 frame/giây thay vì 2. Tắt camera khi máy khóa/tạm dừng.
- Đo trên máy dev: Khi cần ~0.1%, Liên tục ~2–2.6% của 1 nhân CPU, ~90–136 MB RAM (trước khi tối ưu: 12.9%).

## Khởi động cùng Windows

Lần chạy đầu tiên app tự đăng ký vào `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (không cần quyền admin).
Tắt/bật ở menu tray hoặc Cài đặt; app sẽ không tự bật lại nếu bạn đã tắt. Nếu chuyển thư mục app, lần chạy kế tiếp tự cập nhật đường dẫn.
Cấu hình lưu ở `%LOCALAPPDATA%\AutoLock\config.json`.

## Chạy

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python tools\download_models.py     # tải 3 model ONNX (~75 MB) vào models\, kiểm tra SHA-256
.venv\Scripts\pythonw main.py --dry-run           # test ẩn, chỉ ghi log, KHÔNG khóa thật
.venv\Scripts\pythonw main.py                     # chạy thật, ẩn ở tray
.venv\Scripts\pythonw main.py --enroll            # chỉ mở cửa sổ đăng ký khuôn mặt
.venv\Scripts\pythonw main.py --settings          # chỉ mở cửa sổ cài đặt
.venv\Scripts\python -m pytest -q                  # unit test (không ghi vào %LOCALAPPDATA%)
```

Tùy chọn (ghi đè config): `--camera 0 --camera-mode on_demand|continuous --lock 12 --idle-lock 10 --warn 3 --fps 2 --idle-grace 5 --no-person --no-owner --no-tray`.
`--dry-run` không bao giờ đăng ký tự khởi động.
Chỉ chạy một bản cùng lúc (mở bản thứ hai sẽ tự thoát).

### Mã nguồn

| File | Vai trò |
|---|---|
| `main.py` | Điểm vào: tham số dòng lệnh, một bản duy nhất, chọn tiến trình chính / cửa sổ đăng ký / cài đặt |
| `app.py` | Vòng lặp chính: khóa máy, tạm dừng, lịch, nhịp kiểm tra, nạp lại cấu hình |
| `presence.py` | Logic quyết định thuần (phân loại, xác nhận người lạ, đếm giờ khóa, tự khóa khi không thao tác, chính sách camera) |
| `analyzer.py` | Phân tích một frame → kết luận; bám theo + tự học mẫu |
| `vision.py` | YuNet, SFace, YOLOX; cổng chất lượng khuôn mặt; tăng sáng |
| `owner.py` | Thư viện khuôn mặt chủ máy (`owner.npz`), chống trôi, bám theo |
| `camera.py`, `camlock.py` | Camera DirectShow; nhường camera cho cửa sổ đăng ký/cài đặt |
| `strangers.py` | Ảnh người lạ, dọn theo thời hạn |
| `winapi.py` | LockWorkStation, thời gian không thao tác, trạng thái khóa, pin, EcoQoS, registry |
| `paths.py`, `offline.py`, `config.py`, `schedule.py`, `logsetup.py` | Thư mục dữ liệu, chặn mạng, cấu hình, lịch, log |
| `tray.py`, `enroll.py`, `settings_ui.py`, `ui_common.py` | Giao diện |

Model ONNX không nằm trong git (`.gitignore`); `build.ps1` tự gọi `tools\download_models.py`.

## Tray

Icon xanh lá = có mặt, vàng = sắp khóa, đỏ = đã khóa, xám = tạm dừng / không có camera, xanh dương = app khác đang dùng camera.
Menu: tạm dừng 15/30/60 phút, tiếp tục, chế độ camera (Khi cần/Liên tục), tự khóa khi không thao tác (Tắt/5/10/15/30/60 phút/Tùy chỉnh), chỉ chạy theo lịch, đăng ký lại khuôn mặt, cài đặt, chạy cùng Windows, thoát.

## Đóng gói

```
.\build.ps1
```
Tạo ra:
- `dist\AutoLock\AutoLock.exe`: bản chạy trên máy này (dữ liệu ở `%LOCALAPPDATA%\AutoLock`).
- `dist\AutoLock-portable-<ngày>.zip` (~124 MB, giải nén ~215 MB): bản mang sang máy khác. Gói sạch, không chứa cấu hình,
  khuôn mặt, log hay ảnh của máy build. Kèm `HUONG-DAN.txt` cho người nhận.

Script bỏ các file không dùng (~37 MB): backend ffmpeg của OpenCV (app đọc camera qua DirectShow) và codec AVIF của Pillow.

### Chế độ portable

Có thư mục `data\` cạnh `AutoLock.exe` (và ghi được) → mọi dữ liệu nằm trong đó; copy cả thư mục là mang theo cấu hình.
Không có (hoặc thư mục chỉ đọc, ví dụ Program Files) → `%LOCALAPPDATA%\AutoLock`. Xem `paths.py`.
Thư mục `data\` nằm trên ổ mạng, ổ USB/thẻ nhớ hoặc trong thư mục đồng bộ đám mây (OneDrive, Dropbox, Google Drive,
iCloud...) sẽ bị bỏ qua (dùng `%LOCALAPPDATA%\AutoLock`), để ảnh không rời khỏi máy.

### Chỉ chạy cục bộ, ảnh chỉ nằm trên máy này

- Không có mã mạng nào; model nhận diện là file `.onnx` đóng gói sẵn. `offline.py` còn gắn audit hook của Python ngay khi
  khởi động: mọi kết nối socket / tra DNS / HTTP ra ngoài máy (khác loopback) đều bị chặn.
- Ảnh người lạ (`strangers\`) và ảnh mặt thu nhỏ (`learned\`) chỉ được ghi khi thư mục dữ liệu là ổ cứng cục bộ và không
  nằm trong thư mục đồng bộ đám mây (`paths.is_private_local`); nếu không, app không lưu ảnh và ghi cảnh báo vào log.
Cờ "đã bật tự khởi động lần đầu" lưu ở registry `HKCU\Software\AutoLock` (theo từng máy), không nằm trong `config.json`,
để bản portable sang máy mới vẫn tự đăng ký chạy cùng Windows.

Máy đích: Windows 10/11 64-bit, có webcam; không cần Python hay quyền admin. Exe chưa ký số nên SmartScreen có thể cảnh báo
("More info" → "Run anyway"). Máy có nhiều camera (ví dụ camera hồng ngoại Windows Hello): Cài đặt → "Camera số".

## Giới hạn đã biết

- Phát hiện "app khác đang dùng camera" đọc từ registry ConsentStore. Trên bản Windows mới (ví dụ 26300) registry không còn cập nhật theo thời gian thực nên tính năng này không kích hoạt. Không ảnh hưởng nhiều vì Windows 11 cho các app dùng chung camera: AutoLock không chặn Teams/Zoom.
- Người lạ quay lưng/nghiêng mặt (không nhận ra là người lạ) vẫn được person detector tính là có mặt. Lúc chủ máy rời đi thường có khoảng trống > 12s nên máy vẫn khóa trước khi người khác ngồi vào.
- Chưa có liveness check: ảnh chụp mặt chủ máy đặt trước camera có thể giữ máy không khóa.
