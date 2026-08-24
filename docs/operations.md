# Vận hành và xử lý sự cố

## Trạng thái vận hành bình thường

Trạng thái ổn định được kỳ vọng:

- Windows Service `VNPAYRadarScannerAgent`: `Running`, kiểu khởi động `Automatic`.
- Trạng thái scanner: `ready` hoặc tạm thời `busy`.
- Trạng thái thiết bị: `connected` với ADB serial ổn định.
- Request lấy SSO token: HTTP `200`.
- Request heartbeat và claim tới RADAR: HTTP `200`.
- Heartbeat tiếp tục được gửi trong khi scan đang chạy.
- Số dòng pending trong `agent.db` không tăng liên tục.
- Khi bật DAST: Engine `127.0.0.1:8010` trả health/catalog, DAST logical agent có capability và
  `device_status=not_required`.

Dùng Scanner Manager cho các kiểm tra thường xuyên. Tab Diagnostics kiểm tra các thành phần:

1. Client Credentials của VNPAY SSO.
2. APK Scanner `/health`.
3. APK Scanner `/device` và quyền của thiết bị Android.
4. RADAR `/internal/scanner/health` có xác thực.
5. DAST Engine `/health` và `/v1/vulnerabilities` khi DAST worker được bật.

Chạy Diagnostics không ghi heartbeat và không nhận hoặc thực thi scan job. Từ phiên bản `0.6.0`,
bảng kết quả hiển thị trạng thái của từng bước ngay khi chạy xong; không cần chờ cả bốn phép kiểm
tra hoàn tất mới thấy kết quả. Từ `0.7.1`, RADAR health bắt đầu cùng các phép kiểm tra khác, chỉ chờ
token SSO bắt buộc và không chờ kết quả APK Scanner hoặc Android device. Kiểm tra Android vẫn bị
bỏ qua khi scanner đang bận để không ảnh hưởng testcase đang chạy.

Scanner Manager chạy một instance trong mỗi phiên đăng nhập Windows. Nút đóng cửa sổ thu nhỏ ứng
dụng xuống system tray. Menu tray cung cấp các thao tác nhanh: mở Manager, chạy Diagnostics, mở log,
kiểm tra update, Start/Stop/Restart service và Exit.

## Chuyển môi trường RADAR

Một bản phát hành hỗ trợ cả DEV và UAT; không cài hai binary khác nhau. Để chuyển môi trường:

1. Xác nhận không có job đang chạy và chờ Agent gửi hết kết quả của môi trường hiện tại.
2. Dừng `VNPAYRadarScannerAgent` trong tab Overview.
3. Chọn preset **Development**, **UAT** hoặc **Custom** trong tab Configuration.
4. Kiểm tra Agent ID, Client ID/secret và endpoint được hiển thị.
5. Chọn **Save configuration**, sau đó **Install / Reinstall**.
6. Chạy Diagnostics và xác nhận Agent online đúng trên trang Scanners của môi trường mới.

Manager không cho đổi profile khi Service/direct process còn chạy. SQLite outbox của môi trường
cũ được giữ lại và không được gửi sang môi trường mới. Khi môi trường DEV ngừng sử dụng, bỏ DEV
khỏi quy trình vận hành và đổi preset mặc định trong một bản phát hành sau; không tự động xóa
outbox DEV vì có thể còn cần đối soát hoặc rollback.

## Kiểm tra bằng dòng lệnh

```powershell
Get-Service VNPAYRadarScannerAgent

Get-Content `
  C:\ProgramData\VNPAY\RadarScannerAgent\logs\VNPAYRadarScannerAgent.err.log `
  -Tail 100
```

Điều khiển service yêu cầu cửa sổ PowerShell có quyền Administrator:

```powershell
Restart-Service VNPAYRadarScannerAgent
(Get-Service VNPAYRadarScannerAgent).WaitForStatus(
  'Running',
  [TimeSpan]::FromSeconds(30)
)
```

## Đọc hiểu log

Agent ghi log có cấu trúc JSON và WinSW thực hiện log rotation. Các thông báo quan trọng:

| Thông báo hoặc request | Ý nghĩa |
| --- | --- |
| `Scanner agent started` | Đã tải thành công cấu hình và DPAPI secret. |
| `GET .../health 200` | Có thể kết nối tới APK Scanner cục bộ. |
| `GET .../device 200` | Device endpoint đã phản hồi; xem heartbeat để biết trạng thái connected/disconnected. |
| `GET ...:8010/health 200` | DAST Engine local đang hoạt động. |
| `GET .../v1/vulnerabilities 200` | API key Engine hợp lệ và catalog đã được tải. |
| `POST .../token 200` | Keycloak Client Credentials hợp lệ. |
| `GET .../internal/scanner/health 200` | RADAR chấp nhận token Scanner Agent; phép kiểm tra không ghi dữ liệu. |
| `POST .../heartbeat 200` | RADAR đã chấp nhận định danh và trạng thái Agent. |
| `POST .../claim ... 200` | Long poll kết thúc bình thường; phản hồi rỗng nghĩa là không có job trong hàng đợi. |
| `Claimed scanner job` | Agent đã nhận một job và lease token. |
| `Delivered scanner result` | RADAR đã chấp nhận kết quả và dòng outbox đã bị xóa. |
| `Scanner agent loop failed` | Vòng lặp hiện tại gặp lỗi và sẽ thử lại sau khoảng chờ đã cấu hình. |

Không đính kèm `.env`, `client-secret.dpapi` hoặc `agent.db` vào ticket hỗ trợ. Trước tiên,
cung cấp các file log đã rotate và che access token hoặc dữ liệu nhạy cảm không mong muốn trong
kết quả scanner.

## Ma trận xử lý sự cố

| Hiện tượng | Nguyên nhân có thể | Cách xử lý |
| --- | --- | --- |
| Service chưa được cài đặt | Manager chưa hoàn tất **Install / Reinstall** | Lưu cấu hình, cài service với quyền Administrator rồi chạy lại Diagnostics. |
| Service khởi động rồi dừng | Thiếu/sai cấu hình, lỗi truy cập DPAPI hoặc giá trị vi phạm ràng buộc | Đọc service error log mới nhất; kiểm tra các đường dẫn trong ProgramData và cài lại bằng Manager. |
| SSO trả `401` / `invalid_client` | Sai Client ID/secret, client bị tắt hoặc secret đã luân chuyển | Kiểm tra `vnpay-radar-agent`, cập nhật secret qua Manager rồi cài đặt/nâng cấp lại. |
| RADAR trả `401` | Token hết hạn/không hợp lệ hoặc issuer không khớp | Xác nhận RADAR URL và realm của token cùng môi trường; Agent sẽ thử lại một lần với token mới. |
| RADAR trả `403` | Service account thiếu role `scanner-agent` | Gán client role này cho chính service-account user của client. |
| APK Scanner không khả dụng | Container/tiến trình đã dừng hoặc Scanner URL sai | Khởi động APK Scanner và kiểm tra `http://127.0.0.1:8000/health`. |
| DAST Engine không khả dụng | Container dừng, URL/API key sai hoặc catalog rỗng | Kiểm tra `http://127.0.0.1:8010/health`, API key và `/v1/vulnerabilities`; không expose port ra mạng. |
| DAST job ở queued dù Agent online | `engine_testcase_id` không có trong catalog hoặc DAST logical worker chưa bật | So sánh mapping testcase trên RADAR với capability heartbeat và kiểm tra DAST Agent ID riêng. |
| DAST báo thiếu principal | Tên principal trong config chưa có credential hoặc credential đã hết hạn | Admin/PIC mở **Config DAST** của project trên RADAR, cập nhật **DAST test credentials** rồi chạy lại job. |
| DAST poll mất scan sau restart | Engine restart làm mất scan record trong RAM | Agent sẽ xóa checkpoint và chạy lại sau khi lease hợp lệ; kiểm tra idempotency của target trước khi retry. |
| Thiết bị bị ngắt kết nối | USB debugging bị tắt, chưa chấp nhận RSA, lỗi cáp/driver hoặc emulator offline | Kiểm tra APK Scanner `/device` và `adb devices`; `usb.online=false`, `usb.cable_connected=true`, `wifi.online=true` là trạng thái hợp lệ khi `adbhide` đang bật. |
| Job giữ trạng thái queued | Agent offline, capability không khớp hoặc không có Agent đủ điều kiện | Kiểm tra thời điểm heartbeat, `capabilities`, trạng thái scanner/thiết bị và testcase của job. |
| Agent chuyển offline trong khi đang scan | Heartbeat task lỗi hoặc Backend không nhận heartbeat quá ngưỡng offline | Kiểm tra log `Could not send scanner agent heartbeat`, kết nối RADAR và chu kỳ heartbeat. |
| Cùng một máy xuất hiện hai lần | Agent ID khác nhau hoặc service và worker trực tiếp cùng chạy | Dừng tiến trình trùng và chỉ giữ một Agent ID ổn định. |
| Không thấy kết quả trên RADAR | Backend không khả dụng; kết quả có thể vẫn nằm trong SQLite outbox của profile hiện tại | Khôi phục kết nối RADAR và không xóa file `profiles/<profile>/agent.db`; Agent sẽ thử gửi lại trước khi nhận việc mới. |
| Lỗi lease lặp lại | Độ trễ Backend/lỗi mạng hoặc chu kỳ gia hạn quá dài | Kiểm tra kết nối RADAR và so sánh chu kỳ gia hạn với thời hạn lease từ Backend. |
| Setup không thể thay thế file | Service/tiến trình hiện tại vẫn đang giữ file thực thi | Dùng Setup 0.3.1 trở lên để tự động đóng Manager và dừng/khởi động lại service. |
| Manager không kiểm tra được bản mới | Không truy cập được GitHub API, proxy chặn hoặc TLS lỗi | Kiểm tra HTTPS chiều đi tới `api.github.com` và `github.com`, sau đó chọn **Check again**. |
| Tải update thất bại | Asset thiếu, vượt giới hạn hoặc SHA-256 không khớp | Không chạy file đã tải; kiểm tra GitHub Release và file `SHA256SUMS`, rồi thử lại. |
| Service không start sau khi cài lại | Service registration cũ chưa được gỡ hoàn toàn hoặc worker thoát khi khởi động | Mở tab **Logs** và kiểm tra `VNPAYRadarScannerAgent.err.log` cùng `VNPAYRadarScannerAgent.wrapper.log`. Từ bản `0.5.4`, Setup tự dọn registration mồ côi và không xóa application files nếu uninstall service thất bại. |
| Manager đóng sau khi tải update nhưng không mở lại | Setup cũ dùng `taskkill /T`, làm đóng cả process Setup được Manager khởi chạy | Mở lại Manager và chạy **Update now** để tải bản `0.5.7` trở lên. Nếu Manager không mở được, cài Setup mới thủ công một lần. |
| Updater báo lỗi khi đang cài đặt | Setup không dừng/khởi động được service, thiếu file hoặc tiến trình khác đang giữ file | Giữ cửa sổ Updater, chọn **Open logs**, xử lý nguyên nhân rồi chọn **Retry**. Log nằm tại `C:\ProgramData\VNPAY\RadarScannerAgent\logs\updater.log`. |

## Kiểm tra thiết bị trước khi chạy

Trước khi tạo job thật:

1. Xác nhận chỉ có đúng một thiết bị mục tiêu đang online.
2. Xác nhận package mục tiêu đã được cài.
3. Xác nhận APK Scanner báo `ready`.
4. Chạy Diagnostics trong Manager.
5. Chọn một testcase đang báo sẵn sàng trên RADAR và theo dõi toàn bộ vòng đời.
6. Với `TC-MOBI-13`, xác nhận cáp USB còn kết nối và chạy testcase này cuối đợt kiểm thử.

Không kiểm thử trên thiết bị cá nhân hoặc tài khoản ứng dụng cá nhân, trừ khi kế hoạch kiểm thử
cho phép rõ ràng.

## Kiểm tra DAST trước khi chạy

1. Xác nhận DAST Engine chỉ bind `127.0.0.1:8010` và container đang healthy.
2. Cấu hình `ENGINE_BASE_URL_ALLOWLIST` chỉ chứa host được phê duyệt.
3. Chạy Diagnostics và xác nhận DAST Engine có catalog khác rỗng.
4. Kiểm tra DAST Agent trên RADAR báo đúng version, engine type và capability.
5. Đảm bảo tất cả principal của project báo `CONFIGURED` trên RADAR và chưa hết hạn.
6. Chạy một testcase kiểm soát, theo dõi `Queued -> Claimed -> Running -> Completed/Failed`.
7. Xác nhận kết quả chỉ cập nhật scan suggestion, không tự đổi trạng thái thực thi thủ công.

## Khôi phục outbox

Outbox bảo vệ kết quả đã hoàn thành trong thời gian RADAR tạm thời gián đoạn. Khi khôi phục:

- Không xóa hoặc thay thế file `agent.db` của profile đang xử lý.
- Không đổi Agent ID trừ khi có chỉ dẫn từ người phụ trách Backend.
- Khôi phục kết nối SSO/RADAR và khởi động lại service nếu cần.
- Chờ thông báo `Delivered scanner result` trước khi tạo thêm job.

Không có quy trình chỉnh sửa SQL thủ công được hỗ trợ. Chuyển tiếp trường hợp cơ sở dữ liệu hỏng
hoặc kết quả bị từ chối vĩnh viễn cho người phụ trách RADAR Backend, kèm log đã loại bỏ dữ liệu
nhạy cảm và job ID bị ảnh hưởng.

## Xử lý khi secret bị lộ

1. Vô hiệu hóa hoặc luân chuyển Keycloak client secret ngay lập tức.
2. Dừng Agent nếu Agent đang gửi lưu lượng trái phép hoặc bất thường.
3. Kiểm tra event của Keycloak client và hoạt động Agent trên RADAR.
4. Cài secret mới qua Manager.
5. Chạy Diagnostics và một bài quét có kiểm soát.
6. Xóa các bản secret bị lộ khỏi ticket hoặc chat nếu nền tảng hỗ trợ, nhưng không coi việc xóa
   là biện pháp thay thế cho luân chuyển secret.

## Kiểm tra sau nâng cấp

Sau khi Setup hoàn tất:

1. Xác nhận service có trạng thái `Running`.
2. Xác nhận heartbeat tiếp theo trên RADAR hiển thị đúng phiên bản.
3. Xác nhận trạng thái scanner/thiết bị khỏe mạnh.
4. Xác nhận request token, heartbeat và claim trả về `200`.
5. Chạy một testcase có kiểm soát khi bản phát hành thay đổi cơ chế thực thi job hoặc ánh xạ
   payload.

## Giới hạn vận hành đã biết

- Mỗi thời điểm chỉ chạy một job.
- Readiness chỉ phản ánh scanner/thiết bị chính, USB hoặc emulator. Điều kiện chuyên biệt như
  cáp vật lý trên Scanner API cũ, Frida Server và quyền overlay vẫn được APK Scanner kiểm tra
  khi bắt đầu job.
- Agent ghi nhận yêu cầu hủy khi gia hạn lease nhưng chưa ngắt request HTTP cục bộ đang chạy.
- Bản build phát triển chưa được ký số cho tới khi bổ sung code signing vào CI.
- Auto-update yêu cầu HTTPS chiều đi tới GitHub và chỉ hỗ trợ package Windows đã cài bằng Setup.
