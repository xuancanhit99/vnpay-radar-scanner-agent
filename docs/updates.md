# Cập nhật tự động

## Luồng hoạt động

Scanner Manager gọi GitHub Releases API khi khởi động và khi người dùng chọn **Check again**.
Nếu có version Semantic Versioning mới hơn, tab **Overview** hiển thị phiên bản mới và bật nút
**Update now**.

Khi xác nhận cập nhật, Manager thực hiện:

1. Đọc release mới nhất và tìm đúng file Setup cùng file `SHA256SUMS`.
2. Chỉ chấp nhận URL HTTPS thuộc GitHub hoặc `githubusercontent.com`.
3. Tải Setup vào `C:\ProgramData\VNPAY\RadarScannerAgent\updates` với giới hạn 100 MiB.
4. Tính SHA-256 và so sánh với checksum của release.
5. Dừng direct process nếu đang chạy và bàn giao package cho `radar-scanner-updater.exe` chạy
   độc lập trong thư mục `updates`.
6. Updater hiển thị các mốc đóng Manager, dừng service, thay file, khởi động service và xác minh
   cài đặt trong khi Setup chạy silent.
7. Setup giữ nguyên cấu hình, DPAPI secret, log, outbox và tự mở lại Scanner Manager sau khi
   nâng cấp thành công.

File `.partial` bị xóa nếu tải lỗi, vượt giới hạn hoặc checksum không khớp. Manager không chạy
artifact không đạt kiểm tra.

## Điều kiện mạng

Máy Windows cần kết nối HTTPS chiều đi tới:

- `api.github.com`
- `github.com`
- các hostname con của `githubusercontent.com` dùng cho redirect tải release asset

Repository phát hành là public để Manager không cần lưu GitHub PAT. Không chuyển repository về
private khi chưa thay update channel bằng endpoint phân phối nội bộ có xác thực.

## Bootstrap và rollback

- Bản `0.6.0` đồng bộ Scanner Manager/Updater với RADAR dark theme, chuyển truy vấn trạng thái
  Windows Service khỏi UI thread và chỉ tải tab Logs khi người dùng mở. Diagnostics cập nhật từng
  bước `WAITING/RUNNING/PASSED/FAILED` thay vì chờ toàn bộ luồng hoàn tất.
- Manager `0.6.0` chỉ cho phép một instance trong mỗi phiên Windows và có system tray menu để mở
  Manager, chạy Diagnostics, xem log, kiểm tra update và điều khiển service. Nút đóng cửa sổ thu
  nhỏ Manager xuống tray; chọn **Exit** từ tray để thoát hoàn toàn.
- Sau khi người dùng xác nhận **Update now**, Manager khóa navigation, cấu hình, service actions và
  tray actions cho tới khi Updater được mở hoặc quá trình tải thất bại.
- Bản `0.5.9` không gọi các endpoint đọc thiết bị/testcase của APK Scanner khi scanner đang bận.
  Trạng thái heartbeat dùng snapshot ổn định gần nhất, tránh làm đổi kênh ADB giữa lúc chạy
  `TC-MOBI-13`.
- Bản `0.5.8` bổ sung cửa sổ Updater độc lập với Manager. Các bước cài đặt lấy từ trạng thái thật
  do Setup ghi vào Registry; lỗi không làm mất cửa sổ mà hiển thị nguyên nhân, **Open logs** và
  **Retry**. Setup `0.5.8` cũng tự bootstrap Updater khi được Manager cũ gọi bằng chế độ silent,
  vì vậy lần nâng cấp từ `0.5.7` đã có giao diện tiến trình.
- Bản `0.5.7` đổi nhãn quản lý Windows Service thành **Install / Reinstall** để thể hiện đúng
  thao tác cài mới hoặc đăng ký lại service; giữ nguyên bản sửa updater của `0.5.6`.
- Bản `0.5.6` sửa nguyên nhân Setup bị đóng ngay sau khi tải xong: không còn dùng `taskkill /T`
  vì silent Setup là process con của Manager. Setup chỉ đóng các process Manager và tiếp tục nâng
  cấp service bình thường.
- Bản `0.5.5` giữ Manager mở trong lúc chờ UAC, ghi kết quả Setup vào Registry và tự mở lại
  Manager khi silent update thất bại. Màn hình **Software update** hiển thị rõ trạng thái sau khi
  cài đặt thay vì đóng mà không có phản hồi.
- Bản `0.5.4` sửa luồng uninstall/reinstall: chờ service được xóa hoàn toàn, giữ nguyên
  application files nếu uninstall service thất bại và tự dọn service registration mồ côi khi
  chạy Setup mới.
- Bản `0.5.2` sửa readiness của `TC-MOBI-13`: cáp USB đang cắm và kênh ADB Wi-Fi online là
  đủ để scanner tự chuyển sang USB khi bắt đầu testcase.
- Các bản trước `0.4.0` không có updater, vì vậy phải cài `0.4.0` thủ công một lần.
- Bản `0.5.0` nâng cấp thành công nhưng không tự mở lại Manager. Từ `0.5.1`, silent update tự
  relaunch Manager sau khi service đã chạy lại.
- Auto-update chỉ chọn release mới hơn; không tự downgrade.
- Không có nút hủy sau khi Setup bắt đầu thay file ứng dụng. Việc đóng Updater bị khóa trong giai
  đoạn này để tránh để lại bản cài đặt không hoàn chỉnh.
- Khi cần rollback, tải Setup version đã phê duyệt, kiểm tra checksum và chạy thủ công.
- Artifact hiện chưa ký Authenticode. Trước production cần bổ sung ký số và xác minh signer trong
  updater, ngoài bước kiểm tra SHA-256 hiện tại.
