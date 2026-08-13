# Tham chiếu cấu hình

## Nguồn cấu hình

Agent đọc cấu hình qua `pydantic-settings` với tiền tố `RADAR_AGENT_`.
Biến môi trường được ưu tiên hơn giá trị trong `.env`.

Manager chọn đường dẫn cấu hình theo thứ tự:

1. `RADAR_AGENT_MANAGER_CONFIG`, khi được thiết lập rõ ràng.
2. `C:\ProgramData\VNPAY\RadarScannerAgent\.env` đối với bản đã cài đặt.
3. `%LOCALAPPDATA%\VNPAY\RadarScannerAgent\.env` đối với chế độ portable.

Worker chạy trên console đọc `.env` từ thư mục làm việc, trừ khi các giá trị được cung cấp
qua biến môi trường của tiến trình.

## Danh sách cấu hình

| Biến | Bắt buộc | Mặc định / ràng buộc | Mô tả |
| --- | --- | --- | --- |
| `RADAR_AGENT_BASE_URL` | Có | `https://radar.vnpay.dev` | Origin của RADAR Backend. Không thêm API path hoặc endpoint phía sau. |
| `RADAR_AGENT_ID` | Có | `windows-lab-01`; mẫu `[A-Za-z0-9._-]+` | Định danh máy ổn định và duy nhất, dùng cho heartbeat và nhận job. Phải thay giá trị mặc định trên mỗi máy mới. |
| `RADAR_AGENT_DISPLAY_NAME` | Có | `Windows Lab 01` | Tên scanner dễ đọc được hiển thị trên RADAR. |
| `RADAR_AGENT_SCANNER_URL` | Có | `http://127.0.0.1:8000` | Base URL của APK Scanner cục bộ. Chỉ cho phép truy cập qua loopback. |
| `RADAR_AGENT_DAST_ENABLED` | Không | `false` | Bật logical DAST worker trong cùng Windows Service. |
| `RADAR_AGENT_DAST_AGENT_ID` | Khi bật DAST | `<agent-id>-dast` | ID riêng của DAST worker trên RADAR. |
| `RADAR_AGENT_DAST_DISPLAY_NAME` | Khi bật DAST | `<display-name> DAST` | Tên hiển thị của DAST worker. |
| `RADAR_AGENT_DAST_ENGINE_URL` | Khi bật DAST | `http://127.0.0.1:8010` | DAST Engine local, không expose ra mạng. |
| `RADAR_AGENT_DAST_ENGINE_API_KEY_FILE` | Khi bật DAST | DPAPI file | API key engine được mã hoá theo machine scope. |
| `RADAR_AGENT_DAST_TIMEOUT_SECONDS` | Không | `2700` | Trần thời gian một DAST scan. |
| `RADAR_AGENT_TOKEN_URL` | Có | Token endpoint của VNPAY-TEST | OIDC token endpoint đầy đủ của realm Keycloak mục tiêu. |
| `RADAR_AGENT_CLIENT_ID` | Có | `vnpay-radar-agent` | Client ID confidential có service account. |
| `RADAR_AGENT_CLIENT_SECRET` | Chỉ khi khởi tạo | Rỗng | Secret dạng rõ dùng khi chạy từ source hoặc cài service. Tuyệt đối không commit hoặc phân phối giá trị này. |
| `RADAR_AGENT_CLIENT_SECRET_FILE` | Được quản lý tự động | Rỗng | Đường dẫn tới secret nhị phân được DPAPI bảo vệ. Do Manager/service installer thiết lập. |
| `RADAR_AGENT_DATABASE_PATH` | Có | `./agent.db` | SQLite outbox lưu kết quả. Bản cài service ghi đè bằng đường dẫn trong `ProgramData`. |
| `RADAR_AGENT_VERIFY_TLS` | Có | `true` | Kiểm tra chứng thư cho kết nối HTTPS tới VNPAY SSO và RADAR. |
| `RADAR_AGENT_HEARTBEAT_INTERVAL_SECONDS` | Không | `10`, khoảng `5..30` | Chu kỳ báo trạng thái Agent/scanner/thiết bị, chạy độc lập với bài quét. |
| `RADAR_AGENT_POLL_WAIT_SECONDS` | Không | `20`, khoảng `0..25` | Thời gian long-poll khi chờ nhận job. |
| `RADAR_AGENT_LEASE_RENEW_INTERVAL_SECONDS` | Không | `15`, khoảng `5..30` | Khoảng thời gian giữa các lần gia hạn lease khi đang quét. |
| `RADAR_AGENT_SCANNER_TIMEOUT_SECONDS` | Không | `400`, khoảng `30..900` | Thời gian tối đa cho request `/scan` cục bộ. |
| `RADAR_AGENT_RETRY_DELAY_SECONDS` | Không | `5`, khoảng `1..60` | Thời gian chờ sau khi một vòng lặp Agent lỗi trước khi thử lại. |

Các giá trị dạng code ở trên là mặc định của chương trình. Dùng `.env.example` làm mẫu cấu
hình portable; file này chủ động sử dụng định danh máy ở dạng tổng quát.

Model thiết bị không phải là cấu hình do người dùng nhập. Agent tự đọc tên thương mại hoặc model
từ ADB server cục bộ, cache theo serial phần cứng và gửi lên RADAR. `Android Device` chỉ được dùng
nội bộ khi thiết bị chưa kết nối hoặc ADB không trả được thông tin model.

## Ví dụ

```dotenv
RADAR_AGENT_BASE_URL=https://radar.example.vn
RADAR_AGENT_ID=windows-mobile-lab-01
RADAR_AGENT_DISPLAY_NAME=Mobile Security Lab 01
RADAR_AGENT_SCANNER_URL=http://127.0.0.1:8000
RADAR_AGENT_DAST_ENABLED=true
RADAR_AGENT_DAST_AGENT_ID=windows-mobile-lab-01-dast
RADAR_AGENT_DAST_DISPLAY_NAME=Mobile Security Lab 01 DAST
RADAR_AGENT_DAST_ENGINE_URL=http://127.0.0.1:8010
RADAR_AGENT_DAST_ENGINE_API_KEY_FILE=
RADAR_AGENT_TOKEN_URL=https://sso.example.vn/realms/REALM/protocol/openid-connect/token
RADAR_AGENT_CLIENT_ID=vnpay-radar-agent
RADAR_AGENT_CLIENT_SECRET=
RADAR_AGENT_CLIENT_SECRET_FILE=
RADAR_AGENT_DATABASE_PATH=./agent.db
RADAR_AGENT_VERIFY_TLS=true
RADAR_AGENT_HEARTBEAT_INTERVAL_SECONDS=10
RADAR_AGENT_POLL_WAIT_SECONDS=20
RADAR_AGENT_LEASE_RENEW_INTERVAL_SECONDS=15
RADAR_AGENT_SCANNER_TIMEOUT_SECONDS=400
RADAR_AGENT_RETRY_DELAY_SECONDS=5
```

Không đưa secret thật vào tài liệu, ảnh chụp màn hình, file mẫu hoặc source control.

Khi dùng Manager, người vận hành chỉ nhập Engine API key rồi chọn **Install / Reinstall**.
Manager mã hóa API key bằng Windows DPAPI và tự điền đường dẫn file. Token hoặc tài khoản kiểm
thử DAST được Admin/PIC cấu hình tập trung trên RADAR theo từng project; Scanner Manager không
lưu hoặc quản lý các credential này.

Sau khi đã deploy RADAR migration và xác nhận Agent `0.9.0` chạy DAST bình thường, có thể xóa
biến legacy `RADAR_AGENT_DAST_PRINCIPALS_FILE` khỏi `.env` và xóa file
`dast-principals.dpapi` cũ. Agent `0.9.0` bỏ qua cả hai giá trị này; không xóa trước khi hoàn tất
rollout Backend để vẫn có đường quay lại Agent `0.8.x` khi cần.

## Lưu trữ secret

### Windows Service đã cài đặt

Service installer thực hiện:

1. Đọc secret dạng rõ từ cấu hình khởi tạo.
2. Mã hóa secret bằng Windows DPAPI với scope `LocalMachine`.
3. Lưu secret vào `client-secret.dpapi`.
4. Giới hạn quyền đọc file cho `LocalSystem` và local Administrator.
5. Chỉ ghi `RADAR_AGENT_CLIENT_SECRET_FILE` vào `.env` đã cài đặt.

DPAPI với scope theo máy phụ thuộc vào ACL của file. Không nới lỏng quyền của file secret hoặc
sao chép file vào thư mục dùng chung.

### Chế độ portable

Manager sử dụng DPAPI với scope `CurrentUser`. Tài khoản Windows khác, kể cả service account,
không thể giải mã secret đó. Vì vậy cấu hình portable không thể dùng thay thế trực tiếp cho cấu
hình Windows Service.

### Luân chuyển secret

1. Luân chuyển secret trong Keycloak qua kênh quản trị được phê duyệt.
2. Mở Manager với quyền Administrator.
3. Nhập secret mới và chọn **Install / Reinstall**.
4. Chạy Diagnostics.
5. Xác nhận request lấy token, heartbeat và claim đều thành công.

## Quy tắc định danh và môi trường

- Agent ID phải duy nhất trong mỗi môi trường RADAR.
- Giữ nguyên Agent ID qua các lần nâng cấp để RADAR cập nhật đúng bản ghi scanner hiện có.
- Dùng Keycloak client hoặc secret riêng cho development, test, UAT và production theo chính
  sách bảo mật của từng môi trường.
- Trỏ `BASE_URL` và `TOKEN_URL` tới cùng một môi trường.
- Luôn bật kiểm tra TLS. Chỉ dùng `RADAR_AGENT_VERIFY_TLS=false` để xử lý sự cố trong môi
  trường cô lập, có phê duyệt rõ ràng và không dùng cho vận hành thông thường.
- Không đặt query string hoặc endpoint path trong `RADAR_AGENT_BASE_URL`.

## Khuyến nghị về thời gian

- Đặt chu kỳ gia hạn lease ngắn hơn đáng kể so với thời hạn lease do RADAR trả về.
- Giữ chu kỳ heartbeat thấp hơn đáng kể ngưỡng offline của Backend; mặc định `10` giây phù hợp
  với ngưỡng offline `45` giây hiện tại.
- Giữ thời gian poll không quá `25` giây vì contract Backend và validation phía client giới
  hạn ở mức này.
- Chỉ tăng scanner timeout sau khi xác nhận thời lượng dự kiến của testcase. Timeout lớn hơn
  cũng làm chậm quá trình phục hồi khi request tới scanner cục bộ bị treo.
