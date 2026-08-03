# Phát triển và phát hành

## Bộ công cụ

- Windows 10/11 x64 để đóng gói và kiểm thử tích hợp service.
- Python 3.12.
- [`uv`](https://docs.astral.sh/uv/) để quản lý dependency và môi trường ảo.
- PyInstaller để tạo file thực thi cho Worker và Manager.
- NSIS để tạo file Setup.
- WinSW `2.12.0`, được script build tải xuống và kiểm tra checksum.

Cài NSIS trên máy build Windows nếu chưa có:

```powershell
winget install NSIS.NSIS
```

## Cấu trúc repository

```text
vnpay-radar-scanner-agent/
|-- src/radar_agent/
|   |-- service.py          # Vòng lặp Worker chính
|   |-- radar_client.py     # Client có xác thực gọi RADAR API
|   |-- scanner_client.py   # Adapter gọi APK Scanner cục bộ
|   |-- job_runner.py       # Điều phối lease và kết quả
|   |-- outbox.py           # SQLite outbox lưu kết quả
|   |-- manager.py          # Windows Manager dùng tkinter/ttk
|   |-- config_store.py     # Tuần tự hóa .env và tích hợp DPAPI
|   `-- secret_store.py     # Các hàm Windows DPAPI cơ bản
|-- packaging/
|   |-- build.ps1
|   |-- verify-release.ps1
|   |-- installer.nsi
|   |-- install-service.ps1
|   `-- uninstall-service.ps1
|-- tests/
|-- docs/
|-- .env.example
`-- pyproject.toml
```

## GitHub Actions

Repository sử dụng hai workflow:

- `CI`: chạy Ruff, Pytest, build và xác minh package trên mọi pull request và push vào
  `develop`. Artifact preview được giữ 7 ngày.
- `Release`: chạy khi push tag `vMAJOR.MINOR.PATCH`, kiểm tra tag khớp metadata, build lại từ
  tagged commit, xác minh artifact rồi tạo GitHub Release bằng `GITHUB_TOKEN` của workflow.

Các action được ghim theo commit SHA. Pipeline không cần PAT hoặc secret ứng dụng. Chứng thư
Authenticode sẽ được bổ sung dưới dạng GitHub Environment secret khi có quy trình ký production.

## Thiết lập môi trường local

```powershell
uv sync --group dev
Copy-Item .env.example .env
```

Thiết lập client secret dành cho development trong `.env`. Tuyệt đối không thêm `.env`
vào Git.

Chạy Worker trên console:

```powershell
uv run radar-scanner-agent
```

Chạy Manager từ source:

```powershell
uv run radar-scanner-manager
```

Để Manager không tải cấu hình của service đã cài đặt trong quá trình phát triển, ghi đè đường
dẫn:

```powershell
$env:RADAR_AGENT_MANAGER_CONFIG = "$env:TEMP\radar-agent-dev\.env"
uv run radar-scanner-manager
```

## Quality gate

Chạy cả hai phép kiểm tra trước mỗi commit:

```powershell
uv run ruff check src tests
uv run pytest -q
```

Các khu vực kiểm thử quan trọng:

- cache token và làm mới một lần sau phản hồi `401`
- heartbeat độc lập với long polling và quá trình chạy scan
- vòng đời job và gia hạn lease
- độ bền outbox và thứ tự gửi kết quả
- ánh xạ phản hồi từ scanner
- round trip DPAPI theo máy/theo user trên Windows
- tuần tự hóa cấu hình an toàn
- xử lý đường dẫn của Manager và trạng thái Windows Service
- tính nhất quán giữa phiên bản runtime và metadata của dự án

Giữ các test ở trạng thái xác định. Dùng `httpx.MockTransport` để giả lập hành vi HTTP của
dịch vụ từ xa và scanner thay vì gọi môi trường thật từ unit test.

## Contract với Backend

Agent hiện gọi các API:

| Phương thức | Endpoint | Mục đích |
| --- | --- | --- |
| `POST` | `/internal/scanner/agents/heartbeat` | Upsert trạng thái và capability của Agent/scanner/thiết bị |
| `POST` | `/internal/scanner/jobs/claim?wait_seconds=N` | Long-poll và nhận lease cho một job đủ điều kiện |
| `POST` | `/internal/scanner/jobs/{job_id}/start` | Chuyển job đã nhận sang trạng thái running |
| `POST` | `/internal/scanner/jobs/{job_id}/lease` | Gia hạn lease và ghi nhận yêu cầu hủy |
| `POST` | `/internal/scanner/jobs/{job_id}/result` | Gửi trạng thái cuối cùng và kết quả có cấu trúc |

Các Python model trong `src/radar_agent/models.py` là contract phía Agent. Backend trong
`vnpay-radar-platform` là nguồn chính thức. Phải phối hợp và chạy contract test khi thay đổi:

- đường dẫn endpoint hoặc phân quyền
- các trường của claim và lease
- giá trị enum của kết quả
- trường heartbeat và định danh capability
- ánh xạ request/response của scanner

## Bổ sung capability testcase

1. Xác nhận APK Scanner hỗ trợ section/testcase identifier và payload.
2. Thêm capability vào heartbeat payload.
3. Ánh xạ RADAR job sang request scanner cục bộ mà không làm mất trường bắt buộc.
4. Chuẩn hóa kết quả scanner thành `pass`, `fail`, `warning` hoặc `error`.
5. Bổ sung test cho trường hợp thành công, scanner lỗi, timeout và phản hồi sai định dạng.
6. Cập nhật eligibility/validation và giao diện của RADAR Backend.
7. Cập nhật tài liệu kiến trúc, vận hành và phát hành.
8. Chạy contract test với thiết bị và package mục tiêu.

Không quảng bá một capability trước khi toàn bộ luồng có thể thực thi thành công.

## Artifact build

```powershell
.\packaging\build.ps1
```

Quy trình build thực hiện:

1. Đồng bộ dependency.
2. Chạy Pytest và Ruff.
3. Build Worker dạng PyInstaller `onedir`.
4. Build file thực thi Manager bằng PyInstaller với manifest yêu cầu quyền UAC Administrator.
5. Tải WinSW và kiểm tra checksum SHA-256 đã ghim.
6. Tạo file ZIP portable.
7. Biên dịch bộ Setup bằng NSIS.
8. Chạy `verify-release.ps1` để kiểm tra checksum, version metadata, cấu trúc ZIP và runtime
   file không được phép.

Kết quả:

```text
packaging/output/
|-- VNPAYRadarScannerAgent-Portable-<version>-x64.zip
|-- VNPAYRadarScannerAgent-Setup-<version>-x64.exe
`-- VNPAYRadarScannerAgent-<version>-SHA256SUMS.txt
```

Mỗi lần build sẽ xóa các artifact Agent phiên bản cũ trong `packaging/output/` để tránh chọn
nhầm file khi phát hành. Worker, Manager và Setup đều được gắn version metadata của ứng dụng;
WinSW service wrapper giữ version riêng của WinSW.

Các tùy chọn build hữu ích:

```powershell
.\packaging\build.ps1 -SkipTests
.\packaging\build.ps1 -SkipInstaller
```

Chỉ dùng `-SkipTests` để chẩn đoán đóng gói trên máy local, không dùng cho artifact phát hành.

## Quản lý phiên bản

Cập nhật đồng thời:

- `project.version` trong `pyproject.toml`
- `__version__` trong `src/radar_agent/__init__.py`

`tests/test_version.py` sẽ lỗi khi hai giá trị không khớp. Sinh lại `uv.lock` sau khi thay
đổi metadata của dự án:

```powershell
uv lock
```

## Checklist phát hành

1. Xác nhận contract Backend và các capability dự kiến.
2. Chạy Ruff và toàn bộ test suite.
3. Build artifact Setup và portable mà không dùng cờ skip.
4. Xác nhận file ZIP portable chứa `.env.example`, Manager, Worker, WinSW và các script.
5. Xác nhận package không chứa `.env`, file DPAPI, cơ sở dữ liệu, log hoặc secret thật.
6. Kiểm thử cài mới bằng Setup trên một máy Windows sạch.
7. Kiểm thử nâng cấp tại chỗ bằng Setup khi service và Scanner Manager đang chạy.
8. Xác nhận service trở lại trạng thái `Running` và giữ nguyên dữ liệu trong ProgramData.
9. Chạy toàn bộ Diagnostics của Manager trên môi trường mục tiêu.
10. Chạy kiểm thử end-to-end có kiểm soát cho từng capability được quảng bá.
11. Ký số và đóng dấu thời gian cho các file phát hành khi CI có chứng thư ký.
12. Merge commit đã qua CI vào `develop`.
13. Tạo và push Git tag `v<version>` từ đúng commit; GitHub Actions tự build và phát hành.
14. Xác nhận workflow Release thành công và ba asset xuất hiện trên GitHub Release.
15. Công bố checksum SHA-256 qua kênh phát hành được phê duyệt.

## Các điểm cần review về bảo mật

- Chỉ bind APK Scanner và ADB trên interface cục bộ.
- Không ghi token, client secret hoặc dữ liệu rõ của DPAPI vào log.
- Luôn bật kiểm tra TLS.
- Giữ nguyên ACL của secret file khi thay đổi code cài đặt.
- Coi dữ liệu scanner trả về là không tin cậy trước khi đưa vào log hoặc báo cáo.
- Ghim phiên bản và kiểm tra dependency được tải xuống trong quy trình đóng gói.
- Không phát hành artifact phát triển chưa ký số như một bản production.
