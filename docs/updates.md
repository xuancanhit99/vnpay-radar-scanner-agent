# Cập nhật tự động

## Luồng hoạt động

Scanner Manager gọi GitHub Releases API khi khởi động và khi người dùng chọn **Check again**.

- Bản `0.9.1` thêm preset Development/UAT/Custom. Chỉ một profile hoạt động tại một thời điểm;
  mỗi RADAR origin dùng SQLite outbox riêng để không gửi nhầm result hoặc DAST checkpoint.
- Bản `0.8.0` thêm logical DAST worker, đồng bộ config/collection bằng lease, mã hoá API key và
  principal secret bằng DPAPI, hỗ trợ checkpoint/poll/cancel DAST scan và chạy song song với APK.
- Bản `0.9.0` chuyển principal credential về RADAR. Agent nhận config đã ghép secret qua lease;
  Scanner Manager không còn yêu cầu `Protected principals JSON`. Cần deploy RADAR migration
  `202608130002` trước khi nâng Agent.
Nếu có version Semantic Versioning mới hơn, tab **Overview** hiển thị phiên bản mới và bật nút
**Update now**.

Khi xác nhận cập nhật, Manager thực hiện:

1. Đọc release mới nhất và tìm đúng file Setup cùng file `SHA256SUMS`.
2. Chỉ chấp nhận URL HTTPS thuộc GitHub hoặc `githubusercontent.com`.
3. Tải Setup vào `C:\ProgramData\VNPAY\RadarScannerAgent\updates` với giới hạn 160 MiB.
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

- Bản `0.7.7` tự nhận diện tên thiết bị từ ADB với APK Scanner cũ, cache theo serial phần cứng
  và bỏ trường nhập model khỏi Manager. `Android Device` chỉ còn là fallback nội bộ.
- Bản `0.7.6` khai báo AppUserModelID ổn định, dùng ICO đa kích thước tại runtime và đặt
  icon riêng cho shortcut/Apps & Features để tránh Windows Shell giữ icon cũ sau cập nhật.
- Bản `0.7.5` chuyển trạng thái và progress bar tải bản cập nhật vào card **Software update**,
  loại bỏ banner trùng lặp phía trên nội dung nhưng vẫn khóa thao tác trong suốt quá trình.
- Bản `0.7.4` thay toàn bộ icon vẽ tay bằng bộ nhận diện RADAR/VNPAY chính thức cho Manager,
  Updater, system tray, executable, installer, shortcut và danh sách ứng dụng Windows.
- Bản `0.7.3` cân đối lại chiều rộng các cột Diagnostics, giữ cột Detail co giãn và căn phải
  latency để người dùng so sánh thời gian phản hồi dễ hơn.
- Bản `0.7.2` bổ sung spinner động cho Diagnostics, đồng bộ giao diện scrollbar ngang với
  scrollbar dọc và dùng checkbox indicator rõ ràng, nhất quán trong Manager/Updater.
- Bản `0.7.1` chỉ hiển thị **Update now** khi có bản mới, thay spinbox native bằng stepper
  `- / +`, kiểm tra RADAR qua endpoint health có xác thực mà không chờ Android, và giữ log ở
  cuối danh sách nhưng luôn căn ngang về đầu dòng.
- Bản `0.7.0` chuyển toàn bộ Manager và Updater sang PySide6/Qt Widgets với giao diện sáng,
  sidebar cố định và style đồng nhất với RADAR. Các tác vụ mạng, PowerShell và diagnostics vẫn
  chạy nền; từng kết quả diagnostics được cập nhật ngay khi hoàn tất. System tray dùng native Qt,
  cửa sổ update tiếp tục khóa thao tác cho tới khi bàn giao thành công cho Setup.
- Bản `0.6.1` chuyển Manager và Updater về giao diện sáng, giữ màu xanh VNPAY làm điểm nhấn.
  Diagnostics chạy đồng thời các probe độc lập và tái sử dụng cùng snapshot cho heartbeat, giảm
  request lặp. RADAR heartbeat vẫn chờ token và dữ liệu scanner bắt buộc; khi scanner đang bận,
  Diagnostics không gọi endpoint thiết bị để tránh ảnh hưởng testcase đang chạy. Setup cũng chờ
  toàn bộ process Manager thoát và kiểm tra file cũ đã được giải phóng trước khi thay thế; nếu file
  vẫn bị khóa, quá trình nâng cấp báo lỗi thay vì ghi nhận thành công sai.
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
