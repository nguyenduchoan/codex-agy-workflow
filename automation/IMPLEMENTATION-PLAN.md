# Triển khai bộ điều phối Python

Ngày: 2026-09-27. Tiếp tục kế hoạch chính trong `PLAN.md`.

## Phạm vi lượt triển khai

- Viết chương trình độc lập dùng Python standard library (thư viện chuẩn), không cần model (mô hình) để chuyển bước.
- Nhận plan/review (kế hoạch/nhận xét) `.md` từ remote Git (đích đồng bộ mã), kiểm tra phiên bản và mục prompt (chỉ dẫn), rồi giao Antigravity với quyền tương đương `agyf`.
- Adapter (lớp kết nối) Codex CLI (giao diện dòng lệnh) gửi yêu cầu kế hoạch/review qua model đã cấu hình; đường ChatGPT dùng `chatgpt-web/gpt-5.6-sol`, không tự hạ `xhigh`.
- Chỉ fallback (chuyển đường dự phòng) khi sự kiện lỗi có cấu trúc xác nhận hết hạn mức. Nội dung trả lời nhắc đến hạn mức không kích hoạt fallback.
- Lưu state (trạng thái) bên ngoài mã nguồn được push, khóa theo repo, giới hạn thời gian/vòng sửa, ngăn gửi lại hành động chưa biết kết quả.
- Chạy unit/integration test (kiểm thử đơn vị/tích hợp) bằng Git thật với remote mẫu cục bộ và agent giả lập. Không coi test giả lập là bằng chứng ChatGPT/AGY thật.
- Đưa mã và hướng dẫn lên nhánh riêng của repo mẫu sau khi kiểm thử; giữ nguyên bài mẫu trên main để tiếp tục vòng thử thật.

## Giao thức tài liệu

Tài liệu `.md` có một khối JSON ở đầu với `run_id`, `iteration`, `kind`, `reviewed_code_sha`, `status`, sau đó là nhận xét và mục `## Prompt bàn giao cho agy`. Nhận đúng phiên bản đã push; không lấy nội dung trả lời qua clipboard (bộ nhớ sao chép).

`kind` là `plan` hoặc `review`; `status` là `READY`, `CHANGES_REQUESTED`, `PASS`. Chỉ coi thay đổi trong thư mục tài liệu của chính lần chạy là thay đổi tài liệu không làm hết hiệu lực review; thay đổi mã ở bất kỳ đâu khác đều yêu cầu xem lại.

## Kiểm tra bắt buộc

1. Tài liệu thiếu, sai schema (cấu trúc dữ liệu), sai lần chạy, sai SHA (mã phiên bản), hoặc chèn đường dẫn ngoài phạm vi phải bị từ chối.
2. Chấp nhận commit chỉ thêm tài liệu, từ chối mã đổi trong lúc review, repo bẩn, lịch sử phân kỳ hoặc remote đổi.
3. Không giao lại cùng tài liệu sau khi hoàn tất; không tự khởi chạy lại agent khi tiến trình trước bị gián đoạn và chưa rõ kết quả.
4. Timeout (giới hạn thời gian), Ctrl+C và yêu cầu dừng phải kết thúc tiến trình con thuộc lần chạy, lưu trạng thái và không đụng tiến trình thủ công.
5. Review `PASS` chỉ kết thúc sau khi kiểm thử độc lập đạt và mã vẫn khớp phiên bản được review.
6. Đúng tham số `agy --dangerously-skip-permissions`; prompt đi qua stdin (luồng dữ liệu đầu vào), không ghép vào shell command (lệnh hệ thống).
7. Phân biệt lỗi hạn mức có cấu trúc với lỗi mạng/xác thực và văn bản thông thường; không có API key (khóa truy cập API) model trả phí được dùng ngầm.

## Các bước đang chờ người dùng

- Quyết định dùng High cho phép thử tài khoản hiện tại hay chờ đúng xhigh.
- Cầu nối đã được phép khởi chạy sau yêu cầu tiếp tục của người dùng; hiện chờ người dùng hoàn tất xác thực đăng nhập trong cửa sổ riêng.

Các bước trên không cản việc viết/kiểm thử bộ điều phối. Cầu nối đã mở; chưa gửi thêm lượt High.
