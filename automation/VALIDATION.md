# Bằng chứng kiểm thử bộ điều phối

Ngày: 2026-09-27. Đây là bản thử; chưa xác nhận toàn bộ vòng ChatGPT web → GitHub → AGY chạy độc lập.

## Đã đạt

`python3 -m unittest discover -s automation/tests -v`: **29/29 test (kiểm thử) đạt**, lần chạy cuối mất khoảng 35 giây.

Các test dùng Git thật với remote (đích đồng bộ) cục bộ, còn agent (tác nhân) được giả lập:

- Vòng kế hoạch → tài liệu Git → triển khai → review (rà soát) `PASS` → test độc lập → `DONE`; gọi lại sau khi xong không gửi hoặc thực thi trùng.
- Từ chối metadata (dữ liệu mô tả) sai, khóa JSON trùng, kiểu boolean dùng làm số vòng và tệp tài liệu dạng symlink (liên kết tượng trưng).
- Chấp nhận commit (phiên bản Git) chỉ thêm tài liệu; từ chối mã đổi sau review, tài liệu đổi trước lúc giao AGY, repo bẩn, sai remote và lịch sử phân kỳ.
- Tài liệu chưa push (đẩy thay đổi) thì tiếp tục chờ; tìm được tài liệu sau gián đoạn thì nhận lại qua Git mà không gửi model lần nữa.
- Lượt AGY chưa rõ kết quả không tự thực thi lại; khóa repo ngăn hai chương trình cùng chạy.
- Lỗi hạn mức xác định trong sự kiện lỗi mới chuyển native Codex sang web; lỗi mạng hoặc văn bản model nhắc hạn mức không kích hoạt. Hết hạn mức web thì dừng chờ.
- Review `PASS` nhưng test lỗi không được đánh dấu hoàn tất; đổi tệp được bảo vệ hoặc vượt giới hạn vòng thực thi đều bị chặn.
- Timeout (quá thời gian), yêu cầu dừng, thời hạn tổng và kết thúc tiến trình con được kiểm thử bằng tiến trình Python thật.
- Prompt (chỉ dẫn) AGY gửi nguyên vẹn qua stdin (luồng đầu vào), ký tự shell (lệnh hệ thống) được giữ như dữ liệu.

## AGY thật

Đã chạy adapter (lớp kết nối) mới với AGY CLI (giao diện dòng lệnh) `1.2.11` trên repo mẫu, dùng `--dangerously-skip-permissions`, `--input-format stream-json`, `--output-format stream-json`, thời hạn 90 giây.

Prompt chỉ yêu cầu trả một mã xác nhận, không đọc/sửa tệp hoặc gọi công cụ. Kết quả: exit code (mã kết thúc) `0`, trạng thái `SUCCESS`, đúng chuỗi `AGY_STDIN_PILOT_OK`, có `conversation_id` (mã cuộc trò chuyện) thật. Đây là bằng chứng adapter truyền/nhận được với AGY; chưa phải bằng chứng vòng sửa mã mới qua GitHub hoàn tất.

## GitHub thật và cầu nối

- Repo mẫu `nguyenduchoan/codex-agy-workflow`: đã có mã phân trang và bảy test tại `2bfd75ee409fb2c1f662ab1f15f5c264f133f4e4`. Ba test thất bại có chủ đích.
- ChatGPT web đã đọc và phát hiện lỗi, nhưng lượt đó được dừng do thao tác nhập nhiều dòng gửi sớm ở mức High. Chưa có tài liệu review được push; không tính lượt đó là kiểm chứng đúng xhigh.
- Gói `codex-chatgpt-web` `v6.1.1` cho macOS arm64 đã được kiểm tra SHA-256 (mã kiểm tra tính toàn vẹn). Sau khi người dùng yêu cầu tiếp tục và quyền chạy được chấp nhận, launcher (ứng dụng khởi chạy) đã mở với thư mục Codex, dữ liệu cầu nối và hồ sơ trình duyệt riêng.
- Tại thời điểm ghi báo cáo, launcher đang chờ người dùng hoàn tất xác thực đăng nhập Google để vào ChatGPT. Chưa xác minh model/effort (mức suy luận), Full harness (chế độ có công cụ), quyền Git hay việc chạy khi Codex hết hạn mức.

## Còn cần kiểm chứng dịch vụ thật

1. Đăng nhập launcher và xác nhận tài khoản có đúng `xhigh`, hoặc người dùng đồng ý mức khác.
2. Thiết lập Full harness và quyền công cụ bằng tài khoản hiện có; xác nhận điều kiện khóa Tunnel (kênh kết nối) và chi phí. Không bật API (giao diện lập trình) model trả phí.
3. Chạy Codex CLI bằng route (đường định tuyến) web, kiểm tra ChatGPT tự push `.md` đúng schema (cấu trúc) và đúng phiên bản.
4. Chạy bộ điều phối nhận tài liệu, AGY sửa/push, test độc lập và ChatGPT review lại.
5. Kiểm chứng khi Codex thực sự hết hạn mức nhưng ChatGPT còn. Các test lỗi hạn mức hiện tại là mô phỏng, không phải bằng chứng dịch vụ thật.

Tài liệu đối chiếu giao diện: [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode), [Antigravity headless mode](https://antigravity.google/docs/cli/headless/).
