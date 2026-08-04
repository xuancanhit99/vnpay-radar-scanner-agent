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
5. Dừng direct process nếu đang chạy, yêu cầu quyền Administrator qua UAC, khởi chạy Setup ở
   chế độ silent rồi đóng Manager.
6. Setup dừng/khởi động lại Windows Service và giữ nguyên cấu hình, DPAPI secret, log, outbox.
7. Sau khi nâng cấp thành công, Setup tự mở lại Scanner Manager bằng phiên bản mới.

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

- Bản `0.5.4` sửa luồng uninstall/reinstall: chờ service được xóa hoàn toàn, giữ nguyên
  application files nếu uninstall service thất bại và tự dọn service registration mồ côi khi
  chạy Setup mới.
- Bản `0.5.2` sửa readiness của `TC-MOBI-13`: cáp USB đang cắm và kênh ADB Wi-Fi online là
  đủ để scanner tự chuyển sang USB khi bắt đầu testcase.
- Các bản trước `0.4.0` không có updater, vì vậy phải cài `0.4.0` thủ công một lần.
- Bản `0.5.0` nâng cấp thành công nhưng không tự mở lại Manager. Từ `0.5.1`, silent update tự
  relaunch Manager sau khi service đã chạy lại.
- Auto-update chỉ chọn release mới hơn; không tự downgrade.
- Khi cần rollback, tải Setup version đã phê duyệt, kiểm tra checksum và chạy thủ công.
- Artifact hiện chưa ký Authenticode. Trước production cần bổ sung ký số và xác minh signer trong
  updater, ngoài bước kiểm tra SHA-256 hiện tại.
