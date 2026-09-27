# Kế hoạch thử quy trình ChatGPT → GitHub → Antigravity

Ngày: 2026-09-27. Run ID (mã lần chạy): `github-pilot-20260927-01`.
Repo (kho mã nguồn): `nguyenduchoan/codex-agy-workflow`.

## Mục tiêu

ChatGPT web đọc mã mẫu, tự tạo và push (đẩy thay đổi) tài liệu `.md` kèm prompt (chỉ dẫn) bàn giao; chương trình nhận tài liệu qua Git và gọi Antigravity với quyền tương đương `agyf`. Antigravity sửa, chạy test (kiểm thử), push mã; ChatGPT review (rà soát) lần cuối.

Tách kết quả kiểm chứng bàn giao GitHub khỏi khả năng chạy độc lập khi Codex hết hạn mức. Không coi lượt do Codex desktop hiện tại điều khiển là bằng chứng chạy độc lập.

## Các bước

1. Tạo fixture (mã mẫu kiểm thử) phân trang có lỗi cố ý và bảy kiểm thử; xác nhận lỗi trước khi sửa.
2. Push kế hoạch, yêu cầu, mã mẫu và kiểm thử lên repo mẫu đang trống.
3. Yêu cầu ChatGPT đọc đúng phiên bản trên GitHub, tạo `reviews/review-01.md`, chứa phiên bản mã đã đọc và mục `Prompt bàn giao cho agy`, rồi push lên nhánh `main`.
4. Đối chiếu tài liệu thật trên GitHub. Nếu ChatGPT không có quyền ghi, ghi nhận chặn và không giả nhận xét là đã push.
5. Khi tài liệu hợp lệ, đồng bộ và giao Antigravity sửa đúng phạm vi. Giữ nguyên kiểm thử, chạy lại độc lập và đối chiếu mã sau push.
6. Yêu cầu ChatGPT review lần hai và push `reviews/review-02.md` cho đúng phiên bản mới.
7. Kiểm tra/cài thử cầu nối `miuuyy/codex-chatgpt-web` trong môi trường riêng; thử lượt model web từ Codex CLI (giao diện dòng lệnh) và hành động công cụ thật. Chỉ thay đổi cấu hình cần cho môi trường thử.
8. Kiểm chứng chuyển đường khi lỗi hạn mức bằng mô phỏng; xác minh thực tế sau này khi trạng thái tài khoản phù hợp, không cố tiêu hết hạn mức.

## Điều kiện và kết quả

- Chỉ dữ liệu mẫu công khai; không đưa hồ sơ đăng nhập, khóa, cấu hình cá nhân hoặc nhật ký chưa lọc lên repo.
- Giữ `reviewed_code_sha` (phiên bản mã được review) riêng với phiên bản chứa tài liệu review.
- Mỗi bước có giới hạn thời gian; không tự gửi lại nếu chưa xác định lần trước đã hoàn tất hay chưa.
- Không dùng API (giao diện lập trình) model tính phí riêng. Nếu Full harness (chế độ cầu nối có công cụ) cần khóa Tunnel (kênh nối công cụ), kiểm tra điều kiện tài khoản và yêu cầu người dùng hoàn tất bước đăng nhập/cấp quyền khi cần.
- Tối đa ba vòng sửa. Không dùng kết quả công cụ mô phỏng của `dev:chat` làm bằng chứng ghi/push thật.
- Báo cáo cuối phân biệt rõ: đạt, lỗi, bị chặn và chưa thử.
