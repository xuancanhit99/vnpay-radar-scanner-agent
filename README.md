# VNPAY RADAR Scanner Agent

Worker biên chạy trên Windows dành cho VNPAY RADAR. Agent chủ động lấy các job quét APK từ
RADAR Backend, giao việc thực thi cho `apk-scan-api` cục bộ và gửi kết quả về qua HTTPS.

Phiên bản hiện tại hỗ trợ chạy một job tại một thời điểm. Agent lấy catalog động từ APK Scanner,
quảng bá `TC-MOBI-2`, `TC-MOBI-3`, `TC-MOBI-4`, `TC-MOBI-12`, `TC-MOBI-13` và báo readiness
riêng cho từng testcase theo trạng thái thiết bị vật lý, cáp USB hoặc emulator. Với
`TC-MOBI-13`, Agent chấp nhận trạng thái điều khiển qua Wi-Fi khi cáp vật lý vẫn đang cắm;
APK Scanner sẽ tự chuyển sang USB để test rồi khôi phục Wi-Fi.

Phiên bản phát hành dùng Semantic Versioning. Có thể kiểm tra phiên bản tại tab **Overview**
của Scanner Manager, heartbeat trên RADAR, hoặc mục Apps & features của Windows. Từ phiên bản
`0.4.0`, Manager tự kiểm tra GitHub Releases và hỗ trợ cập nhật bằng một nút sau khi xác minh
checksum SHA-256 của bộ Setup.

## Mô hình triển khai

```mermaid
flowchart LR
    User["Người dùng RADAR"] --> Web["RADAR Web"]
    Web --> Backend["RADAR Backend"]
    Agent["Scanner Agent<br/>Windows Service"] -->|"HTTPS 443 chiều đi"| Backend
    Agent -->|"Client Credentials"| SSO["VNPAY SSO"]
    Agent -->|"HTTP localhost"| Scanner["APK Scanner API"]
    Scanner -->|"ADB / USB"| Device["Thiết bị Android hoặc emulator"]
```

Máy Windows không cần IP public hoặc quy tắc firewall cho chiều kết nối vào. Agent chủ động
khởi tạo toàn bộ kết nối tới các dịch vụ từ xa.

## Thành phần

- **Scanner Agent**: worker chạy nền, gửi heartbeat độc lập, nhận job, gia hạn lease, chạy quét
  và gửi kết quả.
- **Scanner Manager**: ứng dụng desktop Windows dùng PySide6/Qt Widgets để cấu hình, quản lý
  service, chẩn đoán và xem log.
- **System tray**: giữ Manager chạy nền, chỉ cho phép một cửa sổ và cung cấp thao tác nhanh với
  Diagnostics, log, update và Windows Service.
- **Scanner Updater**: tiến trình desktop độc lập hiển thị các mốc nâng cấp trong lúc Manager đóng
  và Setup thay thế file ứng dụng.
- **SQLite outbox**: hàng đợi bền vững cục bộ dành cho kết quả chưa gửi được. PostgreSQL của RADAR
  vẫn là nguồn dữ liệu chính thức.
- **Windows Service wrapper**: WinSW chạy Agent dưới tài khoản `LocalSystem`, tự động khởi động
  có độ trễ và tự khởi động lại khi gặp lỗi.

## Bắt đầu nhanh

### Cài đặt bằng bộ Setup

1. Khởi động APK Scanner cục bộ tại `http://127.0.0.1:8000`.
2. Kết nối thiết bị Android đã được cấp quyền hoặc khởi động emulator.
3. Chạy `VNPAYRadarScannerAgent-Setup-<version>-x64.exe` với quyền Administrator.
4. Mở **RADAR Scanner Manager** và nhập các giá trị phù hợp với môi trường.
5. Chọn **Install / Reinstall**, sau đó chạy toàn bộ kiểm tra trong tab **Diagnostics**.

Xem [Hướng dẫn cài đặt](docs/installation.md) để biết các điều kiện tiên quyết, cấu hình
Keycloak, chế độ portable, quy trình nâng cấp và gỡ cài đặt.

### Chạy từ mã nguồn

```powershell
Copy-Item .env.example .env
# Thiết lập RADAR_AGENT_CLIENT_SECRET trong .env trước khi chạy.
uv sync --group dev
uv run radar-scanner-agent
```

Không commit `.env`, file DPAPI, cơ sở dữ liệu SQLite, log hoặc artifact được sinh ra khi build.

## Cấu hình định danh bắt buộc

Tích hợp mặc định trên môi trường test sử dụng một service account Keycloak riêng:

- Client ID: `vnpay-radar-agent`
- Loại client: confidential
- Service accounts: bật
- Standard Flow, Implicit Flow và Direct Access Grants: tắt
- Client role gán cho chính service-account user của client: `scanner-agent`

Agent không cần role partner, SPI hoặc HR-sync của VNPAY SSO.

## Tài liệu

- [Kiến trúc và vòng đời job](docs/architecture.md)
- [Cài đặt và nâng cấp](docs/installation.md)
- [Tham chiếu cấu hình](docs/configuration.md)
- [Vận hành và xử lý sự cố](docs/operations.md)
- [Phát triển và phát hành](docs/development.md)
- [Cập nhật tự động](docs/updates.md)

## Kiểm tra khi phát triển

```powershell
uv sync --group dev
uv run ruff check src tests
uv run pytest -q
```

Build bộ Setup cho Windows và file ZIP portable:

```powershell
.\packaging\build.ps1
```

Artifact được ghi vào `packaging/output/`, gồm bộ Setup, ZIP portable và file checksum
`SHA256SUMS`. Bản phát hành được công bố tại
[GitHub Releases](https://github.com/xuancanhit99/vnpay-radar-scanner-agent/releases).
Artifact dành cho phát triển hiện chưa được ký số; bản phát hành production phải được ký
Authenticode trong CI.

## Dự án liên quan

Backend API, database migration, giao diện quản lý scanner job và các quy tắc phân quyền thuộc
trách nhiệm của
[`vnpay-radar-platform`](https://git.vnpay.vn/ansp/application-security/vnpay-radar-platform).
Các thay đổi ở Agent và Backend phải được kiểm thử contract cùng nhau trước khi phát hành.
