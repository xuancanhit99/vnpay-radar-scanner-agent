# Kiến trúc

## Mục đích

Scanner Agent kết nối một hệ thống RADAR với các APK Scanner phải chạy trên máy Windows có
thiết bị Android hoặc emulator cục bộ. Kiến trúc này không yêu cầu mở ADB, Scanner API hoặc máy
Windows cho lưu lượng mạng chiều vào.

Agent là một worker thực thi. Agent không quản lý người dùng, định nghĩa bài quét, lịch sử job,
phân quyền hoặc báo cáo. Các chức năng này vẫn thuộc `vnpay-radar-platform`.

## Thành phần

| Thành phần | Trách nhiệm |
| --- | --- |
| RADAR Web | Tạo và hiển thị scanner job. Web không bao giờ kết nối trực tiếp tới Agent. |
| RADAR Backend | Quản lý job, lease, phân quyền, kết quả và dữ liệu báo cáo lâu dài. |
| VNPAY SSO | Cấp access token ngắn hạn của service account cho Agent. |
| Scanner Agent | Chủ động lấy việc, điều phối thực thi, gia hạn lease và gửi kết quả. |
| APK Scanner API | Thực thi testcase trên môi trường Android cục bộ. |
| Thiết bị Android/emulator | Chạy package Android mục tiêu. |
| SQLite outbox | Lưu kết quả đã hoàn thành cho tới khi RADAR chấp nhận. |

## Ranh giới mạng và tin cậy

```mermaid
flowchart TB
    subgraph Remote["Dịch vụ từ xa"]
        SSO["VNPAY SSO"]
        Radar["RADAR Backend"]
    end

    subgraph Windows["Máy Windows chạy scanner"]
        Manager["Scanner Manager"]
        Agent["Scanner Agent service"]
        Outbox[("SQLite outbox")]
        Scanner["APK Scanner API<br/>127.0.0.1:8000"]
        ADB["ADB server"]
        Device["Thiết bị Android/emulator"]
    end

    Manager --> Agent
    Agent --> Outbox
    Agent -->|"HTTPS 443"| SSO
    Agent -->|"HTTPS 443"| Radar
    Agent -->|"HTTP loopback"| Scanner
    Scanner --> ADB --> Device
```

Kết nối bắt buộc:

| Chiều kết nối | Đích | Mục đích |
| --- | --- | --- |
| Đi ra ngoài | VNPAY SSO token endpoint, HTTPS 443 | Lấy token bằng Client Credentials |
| Đi ra ngoài | RADAR Backend, HTTPS 443 | Gọi API heartbeat, claim, lease và result |
| Localhost | APK Scanner API, mặc định HTTP 8000 | Kiểm tra health, trạng thái thiết bị và thực thi quét |
| Cục bộ | ADB và USB | APK Scanner điều khiển thiết bị |

Không mở cổng APK Scanner `8000` hoặc cổng ADB `5037` ra Internet.

## Vòng đời job

```mermaid
sequenceDiagram
    participant UI as RADAR Web
    participant API as RADAR Backend
    participant Agent as Scanner Agent
    participant Scanner as APK Scanner
    participant DB as SQLite outbox

    UI->>API: Tạo scan job
    Agent->>API: Gửi heartbeat
    Agent->>API: Nhận job (long polling)
    API-->>Agent: Trả job và lease token
    Agent->>API: Đánh dấu job đã bắt đầu
    par Thực thi quét
        Agent->>Scanner: POST /scan
        Scanner-->>Agent: pass / fail / warning / error
    and Duy trì lease
        loop Cho tới khi quét xong
            Agent->>API: Gia hạn lease
        end
    end
    Agent->>DB: Lưu kết quả
    Agent->>API: Gửi kết quả
    API-->>Agent: Chấp nhận
    Agent->>DB: Xóa kết quả đã gửi
    UI->>API: Đọc trạng thái/kết quả mới
```

Worker chạy hai vòng lặp độc lập:

1. Vòng heartbeat đọc trạng thái scanner/thiết bị và gửi về RADAR mỗi
   `RADAR_AGENT_HEARTBEAT_INTERVAL_SECONDS`, kể cả khi một bài quét đang chạy.
2. Vòng worker gửi các kết quả còn tồn trong outbox rồi long-poll để nhận một job.
3. Worker khởi động job đã nhận và gia hạn lease ở background.
4. Worker thực thi testcase qua scanner cục bộ.
5. Worker lưu kết quả vào SQLite trước khi gửi tới RADAR.

Thứ tự này ưu tiên độ bền của kết quả hơn việc nhận job mới. Nếu RADAR không khả dụng khi
outbox đang có dữ liệu chờ, Agent sẽ thử gửi lại trước khi nhận thêm job. Vòng worker chỉ bắt
đầu sau khi Backend chấp nhận heartbeat đầu tiên.

## Xác thực và phân quyền

Agent sử dụng OAuth 2.0 Client Credentials với confidential client `vnpay-radar-agent`.
Access token có thời hạn ngắn và được cache trong bộ nhớ. Khi một request nhận
`401 Unauthorized`, Agent làm mới token một lần và thử lại một lần.

RADAR chỉ chấp nhận các endpoint dành cho Agent khi token chứa client role `scanner-agent`.
Client secret được bảo vệ bằng Windows DPAPI và không bao giờ được đưa vào heartbeat, kết quả
job hoặc log.

## Cơ chế lease và outbox

- Phản hồi claim chứa job, lease token và thời hạn lease.
- Agent gia hạn lease theo `RADAR_AGENT_LEASE_RENEW_INTERVAL_SECONDS`.
- Payload kết quả được insert hoặc replace theo `job_id` trong SQLite outbox.
- Một dòng outbox chỉ bị xóa sau khi RADAR Result API chấp nhận dữ liệu.
- SQLite không thay thế PostgreSQL của RADAR và không được dùng để lập báo cáo.

## Khả năng và giới hạn hiện tại

- Capability được lấy động từ `GET /testcases` của APK Scanner. Bản hiện tại hỗ trợ
  `TC-MOBI-2`, `TC-MOBI-3`, `TC-MOBI-4`, `TC-MOBI-12`, `TC-MOBI-13`.
- Heartbeat báo readiness riêng cho từng testcase; USB, thiết bị chính và emulator được đánh giá
  độc lập. `TC-MOBI-13` không yêu cầu USB ADB phải online từ trước: khi `adbhide` đang bật,
  Agent có thể điều khiển qua Wi-Fi và APK Scanner tự kiểm tra cáp rồi chuyển sang USB. Với
  Scanner API cũ chưa trả trạng thái cáp, Agent chỉ precheck có USB hoặc Wi-Fi đang online.
- Mức đồng thời: một job cho mỗi tiến trình Agent.
- Không chạy worker trực tiếp và Windows Service cùng lúc trên một máy.
- Yêu cầu hủy job từ RADAR được ghi nhận khi gia hạn lease, nhưng request đang chạy tới scanner
  hiện chưa bị ngắt.
- Phiên bản Agent hiện tại chưa triển khai upload evidence. Phản hồi từ scanner được gửi dưới
  dạng kết quả có cấu trúc.
- Trạng thái APK Scanner, kết nối thiết bị và readiness từng testcase được báo cáo độc lập trong
  mỗi heartbeat.

Mọi capability testcase mới đều cần thay đổi đồng bộ ở APK Scanner, ánh xạ payload của Agent,
validation của RADAR Backend, giao diện và contract test.
