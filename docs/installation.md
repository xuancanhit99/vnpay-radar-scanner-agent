# Cài đặt và nâng cấp

## Điều kiện tiên quyết

### Máy Windows mục tiêu

- Windows 10 hoặc Windows 11, x64.
- Có quyền local Administrator để chạy bộ Setup và quản lý Windows Service.
- APK Scanner đang chạy tại `http://127.0.0.1:8000`.
- ADB đã được cài đặt trong môi trường APK Scanner.
- Có thiết bị Android đã bật USB debugging và chấp nhận RSA authorization, hoặc emulator
  được hỗ trợ.
- Package Android mục tiêu đã được cài trên thiết bị được chọn.
- Có kết nối HTTPS chiều đi tới VNPAY SSO và RADAR Backend.

Máy đích không cần cài Python khi sử dụng bộ Setup hoặc package portable.

### Keycloak client

Tạo mới hoặc kiểm tra client sau trong realm VNPAY SSO của môi trường mục tiêu:

| Cấu hình | Giá trị |
| --- | --- |
| Client ID | `vnpay-radar-agent` |
| Client authentication | Bật, confidential client |
| Service accounts | Bật |
| Standard Flow | Tắt |
| Implicit Flow | Tắt |
| Direct Access Grants | Tắt |
| Role của service account | Client role `scanner-agent` |

Dùng client secret riêng cho từng môi trường. Luân chuyển secret ngay nếu secret xuất hiện trong
tin nhắn, ticket, ảnh chụp màn hình, repository hoặc gói log.

## Cách cài đặt khuyến nghị: file Setup

1. Nhận file `VNPAYRadarScannerAgent-Setup-<version>-x64.exe` và checksum SHA-256 từ kênh
   phát hành đã được phê duyệt.
2. Kiểm tra checksum trước khi chạy.
3. Chạy Setup với quyền Administrator.
4. Mở **RADAR Scanner Manager** từ menu Start hoặc shortcut trên desktop.
5. Trong tab **Configuration**, thiết lập tối thiểu:
   - RADAR URL
   - Agent ID duy nhất và tên hiển thị
   - APK Scanner URL
   - SSO token URL
   - Client ID và client secret
   - model thiết bị
6. Chọn **Save configuration**.
7. Chọn **Install / upgrade** trong tab Overview.
8. Mở **Diagnostics** và xác nhận cả bốn phép kiểm tra đều thành công.

Manager yêu cầu quyền nâng cao vì ứng dụng quản lý service cấp máy và secret DPAPI với scope
theo máy. Để trống trường Client secret sẽ giữ nguyên secret hiện có.

## Cấu trúc sau khi cài đặt

| Hạng mục | Đường dẫn |
| --- | --- |
| Thư mục chương trình | `C:\Program Files\VNPAY\Radar Scanner Agent` |
| File thực thi Worker | `C:\Program Files\VNPAY\Radar Scanner Agent\agent\radar-scanner-agent.exe` |
| File thực thi Manager | `C:\Program Files\VNPAY\Radar Scanner Agent\radar-scanner-manager.exe` |
| Cấu hình | `C:\ProgramData\VNPAY\RadarScannerAgent\.env` |
| DPAPI secret | `C:\ProgramData\VNPAY\RadarScannerAgent\client-secret.dpapi` |
| SQLite outbox | `C:\ProgramData\VNPAY\RadarScannerAgent\agent.db` |
| Log của service | `C:\ProgramData\VNPAY\RadarScannerAgent\logs` |
| Windows Service | `VNPAYRadarScannerAgent` |

Service chạy dưới tài khoản `LocalSystem`, tự động khởi động có độ trễ và tự khởi động lại khi
gặp lỗi bất thường. Người thực hiện cài đặt có quyền chỉ đọc với thư mục log. Secret và outbox
chỉ cho phép `LocalSystem` và local Administrator truy cập.

## Kiểm tra bản cài đặt

Ưu tiên dùng tab Overview và Diagnostics trong Manager. Các lệnh PowerShell tương đương:

```powershell
Get-Service VNPAYRadarScannerAgent
Get-Content `
  C:\ProgramData\VNPAY\RadarScannerAgent\logs\VNPAYRadarScannerAgent.err.log `
  -Tail 100
```

Quá trình khởi động khỏe mạnh có request thành công tới:

- `/health` cục bộ
- `/device` cục bộ
- VNPAY SSO token endpoint
- RADAR `/internal/scanner/agents/heartbeat`
- RADAR `/internal/scanner/jobs/claim`

## Nâng cấp

Chạy file Setup phiên bản mới hơn với quyền Administrator. Khi service đã tồn tại, Setup sẽ:

1. Phát hiện và dừng service.
2. Thay thế các file chương trình.
3. Giữ nguyên cấu hình, DPAPI secret, log và SQLite outbox trong `ProgramData`.
4. Khởi động lại service.

Sau mỗi lần nâng cấp, kiểm tra phiên bản/trạng thái heartbeat của service và chạy Diagnostics
trong Manager. Không xóa `agent.db` khi có thể vẫn còn kết quả đang chờ gửi.

## Chế độ portable

Giải nén `VNPAYRadarScannerAgent-Portable-<version>-x64.zip` và chạy
`radar-scanner-manager.exe`.

- Cấu hình được lưu tại `%LOCALAPPDATA%\VNPAY\RadarScannerAgent\`.
- Client secret dùng DPAPI theo user hiện tại.
- Chọn **Run directly** thay vì cài service.
- Giữ Manager ở trạng thái mở hoặc thu nhỏ. Khi đóng Manager, tiến trình Agent chạy trực tiếp
  cũng bị dừng sau bước xác nhận.

Chế độ chạy trực tiếp bị khóa khi `VNPAYRadarScannerAgent` đang chạy để tránh một máy nhận job
hai lần.

## Chạy từ mã nguồn

Điều kiện cho máy phát triển:

- Python 3.12 x64
- `uv`

```powershell
Copy-Item .env.example .env
# Sửa .env và thiết lập RADAR_AGENT_CLIENT_SECRET.
uv sync --group dev
uv run radar-scanner-agent
```

`.env.example` trong source dùng `./agent.db`. Trình cài Windows Service luôn ghi đè đường
dẫn cơ sở dữ liệu bằng vị trí được bảo vệ trong `ProgramData`.

## Cài service thủ công

Từ cửa sổ PowerShell có quyền Administrator trong package portable đã giải nén:

```powershell
.\install-service.ps1 -ConfigFile C:\secure\path\radar-agent.env
```

Cấu hình khởi tạo phải chứa `RADAR_AGENT_CLIENT_SECRET`. Trình cài đặt mã hóa giá trị này bằng
DPAPI theo máy, ghi tham chiếu tới secret file trong cấu hình đã cài và không sao chép secret
dạng rõ.

## Gỡ cài đặt

Dùng **Installed apps** của Windows hoặc chạy PowerShell với quyền Administrator:

```powershell
.\uninstall-service.ps1
```

Mặc định, quá trình gỡ cài đặt giữ lại `ProgramData`, bao gồm kết quả outbox chưa gửi. Chỉ xóa
dữ liệu sau khi xác nhận không cần giữ lại:

```powershell
.\uninstall-service.ps1 -RemoveData
```

## Bản build phát triển chưa ký số

Artifact phát triển hiện chưa được ký Authenticode. Chỉ phân phối qua kênh được phê duyệt và
gửi checksum SHA-256 qua một kênh riêng. Bản phát hành production phải được CI ký số và đóng
dấu thời gian trước khi phân phối.
