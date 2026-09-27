# Bộ điều phối Codex → ChatGPT web → GitHub → Antigravity

Bản thử dùng Python standard library (thư viện chuẩn), chạy trên macOS/Linux với Python 3.10 trở lên và Git. Chương trình tự chuyển bước, giữ trạng thái và nhận tài liệu qua Git; các bước đó không cần một model (mô hình) điều phối bên ngoài.

Đường ChatGPT web cần cầu nối `miuuyy/codex-chatgpt-web` đã được thiết lập và kiểm chứng riêng. Bản này chưa được xác nhận hoàn tất toàn bộ vòng dịch vụ thật; xem `VALIDATION.md`.

## Các thành phần

- `workflow.py`: CLI (giao diện dòng lệnh), quản lý trạng thái, kiểm tra Git, gọi Codex/AGY và kiểm thử độc lập.
- `example-config.json`: cấu hình mẫu; sửa đường dẫn tuyệt đối tới checkout (bản sao repo cục bộ) dùng để thực thi. Giữ bản cấu hình thật bên ngoài repo.
- `tests/test_workflow.py`: kiểm thử hành vi bằng Git thật và agent (tác nhân) giả lập, không cần mạng hay subscription (gói thuê bao).

Luồng: `PLANNING` → `WAITING_DOCUMENT` → `READY_TO_IMPLEMENT` → `IMPLEMENTING` → `TESTING` → `REVIEWING` → `WAITING_DOCUMENT`. Review (rà soát) `PASS` chỉ tới `DONE` sau khi kiểm thử độc lập đạt. Lỗi chưa rõ kết quả tới `NEEDS_INPUT`; hết hạn mức cả đường khả dụng tới `WAITING_QUOTA`.

## Chuẩn bị và chạy

1. Đặt `repo`, `remote_url`, `branch`, `test_command` trong bản sao cấu hình. `origin` và URL (địa chỉ) push phải trùng chính xác `remote_url`; checkout phải sạch và ở đúng nhánh.
2. Đăng nhập Codex bằng ChatGPT subscription và đăng nhập Antigravity theo cách hiện có. Adapter (lớp kết nối) dùng `gpt-6-astra`/`xhigh` để lập kế hoạch. Nó từ chối môi trường chứa `OPENAI_API_KEY` hoặc `CODEX_API_KEY` và buộc phương thức đăng nhập ChatGPT khi gọi Codex.
3. Để bật bước web, cần cầu nối chạy sẵn, model `chatgpt-web/gpt-5.6-sol` đúng effort (mức suy luận), và quyền công cụ/ghi Git đã kiểm chứng. Sau đó đặt `web_enabled: true`; `codex_home` có thể trỏ đến cấu hình Codex thử riêng của cầu nối. Chỉ đổi `web_effort` từ `xhigh` khi người dùng đã chấp nhận mức khác.
4. Lưu yêu cầu vào một tệp văn bản bên ngoài checkout rồi chạy các lệnh bên dưới. `--config` trỏ đến bản cấu hình thật.

```sh
python3 automation/workflow.py --config /absolute/private/pilot.json doctor
python3 automation/workflow.py --config /absolute/private/pilot.json init \
  --run-id pilot-001 --goal-file /absolute/private/goal.txt
python3 automation/workflow.py --config /absolute/private/pilot.json run --max-wait 600
python3 automation/workflow.py --config /absolute/private/pilot.json status
```

Thêm `--review-existing` vào `init` để bắt đầu bằng review mã đã có, bỏ qua bước lập kế hoạch. Dùng `step` thay `run` để thực hiện một bước có thể kiểm tra. `run` có thời hạn tổng cho tiến trình agent/test; thao tác Git đang chạy có thời hạn riêng tối đa 45 giây và dừng tiến trình có khoảng chờ ngắn.

`doctor` chỉ kiểm tra checkout, lệnh và sự hiện diện biến môi trường chứa khóa; không chứng minh phiên đăng nhập hay quyền công cụ đang hoạt động. Cấu hình mặc định tắt web; chương trình dừng trước khi gửi lượt web nếu chưa bật.

Codex chạy `workspace-write` (quyền ghi trong workspace), cho phép mạng trong phạm vi đó và không chờ xác nhận tương tác. Nếu công cụ hoặc chính sách không cho phép commit/push (ghi/đẩy phiên bản Git), chương trình giữ trạng thái chưa hoàn tất; phải giải quyết quyền trong môi trường thử, không coi thông báo bằng lời là đã ghi Git. Full harness (cầu nối có công cụ) phải được kiểm chứng với chính cấu hình này.

## Bàn giao `.md` qua Git

Tài liệu chính thức đặt tại `workflow-runs/<run_id>/plan.md` hoặc `review-01.md`, `review-02.md`... Khi bắt đầu bằng plan, iteration (số vòng) là `0`; review đầu tiên sau triển khai là `1`. Khi bắt đầu bằng review mã có sẵn, vòng đầu là `1`.

Định dạng tối thiểu:

````markdown
```json
{
  "run_id": "pilot-001",
  "iteration": 1,
  "kind": "review",
  "reviewed_code_sha": "<full Git SHA>",
  "status": "CHANGES_REQUESTED"
}
```

## Nhận xét

Mô tả lỗi, vị trí, bằng chứng và tiêu chí kiểm thử.

## Prompt bàn giao cho agy

Đọc nhận xét, sửa đúng phạm vi, giữ nguyên kiểm thử được bảo vệ,
chạy kiểm thử rồi commit và push mã.
````

`kind: plan` dùng `status: READY`; `kind: review` dùng `CHANGES_REQUESTED` hoặc `PASS`. Mục prompt (chỉ dẫn) luôn bắt buộc; với `PASS`, ghi `Không cần sửa`.

Chương trình lấy nội dung từ phiên bản Git đã xác minh, không lấy bản `.md` từ clipboard (bộ nhớ sao chép). Nó kiểm tra đúng lần chạy, vòng, SHA (mã phiên bản), tệp thường và kích thước. Chỉ thay đổi `.md` trong thư mục của chính lần chạy được coi là thay đổi tài liệu; mọi thay đổi mã khác sau phiên bản được review đều khiến quy trình dừng để xem lại.

Lệnh `prompt` in yêu cầu tương ứng với trạng thái hiện tại. Có thể dùng khi kiểm chứng thao tác gửi thủ công; sau khi ChatGPT tự push tài liệu, dùng `reconcile document` để nhận qua Git. Chế độ này không phải bằng chứng tự động hóa trình duyệt.

## Antigravity và kết quả thực thi

Chương trình gọi trực tiếp `agy --dangerously-skip-permissions`, tương đương alias (tên lệnh rút gọn) `agyf`, với thời hạn rõ ràng. Prompt gửi bằng một thông điệp JSON qua stdin (luồng đầu vào), không ghép vào shell command (lệnh hệ thống). Chỉ dùng `conversation_id` (mã cuộc trò chuyện) do lần chạy trả lại, không chọn cuộc trò chuyện gần nhất.

AGY phải commit/push mã và trả trạng thái kết thúc `SUCCESS`. Bộ điều phối kiểm tra repo sạch, mã cục bộ khớp remote, không viết lại lịch sử, không đổi tệp được bảo vệ hoặc tài liệu reviewer (bên rà soát), và có thay đổi mã thật. Kiểm tra phạm vi là bước phát hiện sau thực thi, không phải sandbox (môi trường giới hạn quyền): `agyf` vẫn có quyền đầy đủ như người dùng đã chọn.

Sau đó bộ điều phối chạy test độc lập. Nếu test trả lỗi bình thường, bằng chứng được đưa vào yêu cầu review tiếp theo; timeout (quá thời gian) hoặc ngắt thao tác yêu cầu đối chiếu lại. Tổng số vòng thực thi tối đa là ba. Review `PASS` với test lỗi không được đánh dấu hoàn tất.

## Dừng và khôi phục

```sh
python3 automation/workflow.py --config /absolute/private/pilot.json stop
python3 automation/workflow.py --config /absolute/private/pilot.json reconcile document
python3 automation/workflow.py --config /absolute/private/pilot.json reconcile implementation
python3 automation/workflow.py --config /absolute/private/pilot.json reconcile retry-request
```

- `stop` ghi yêu cầu dừng để tiến trình đang sở hữu lần chạy kết thúc nhóm tiến trình con của nó. Ctrl+C cũng dừng nhóm đó và lưu trạng thái. Không đụng phiên AGY thủ công.
- `reconcile document` chỉ đối chiếu Git và nhận tài liệu đã có, không gửi lại yêu cầu model.
- `reconcile implementation` dùng khi lượt AGY bị ngắt nhưng mã đã được commit/push. Phải bảo đảm tiến trình AGY cũ đã kết thúc; lệnh kiểm tra mã và test rồi yêu cầu review mới, không chạy AGY lần nữa.
- `reconcile retry-request` là thao tác người vận hành cho phép thử gửi lại sau khi đã đối chiếu. Nếu tài liệu tồn tại thì nhận tài liệu, không gửi lặp. Không cho dùng lệnh này để chạy lại lượt AGY chưa rõ kết quả.

Sau khi chỉnh riêng `web_enabled`, `web_effort` hoặc `codex_home` trong cấu hình, dùng `update-config` để cập nhật lần chạy; lệnh không khởi chạy agent. Không đổi repo, nhánh, lệnh hoặc giới hạn giữa một lần chạy. Hành động đang chờ kết quả phải được đối chiếu trước khi cập nhật cấu hình.

State (trạng thái) và log (nhật ký) nằm ở Git common directory (thư mục dữ liệu Git dùng chung), dưới `agy-workflow/`. Tệp trạng thái được ghi atomic (thay thế trọn vẹn), log được giới hạn quyền truy cập và không nằm trong cây mã được commit. Log có thể chứa nội dung dự án; giữ riêng, không đẩy lên repo public. Khóa theo repo giới hạn một tiến trình điều phối tại một thời điểm.

Nếu toàn bộ chương trình bị `SIGKILL` hoặc máy tắt, việc gọi công cụ đã bắt đầu có thể chưa rõ kết quả. Chương trình không hứa exactly-once (thực thi đúng một lần) qua mọi sự cố và không tự chạy lại thao tác đó. Kiểm tra tiến trình còn sống và Git trước khi reconcile.

## Hạn mức và kiểm thử

Fallback (chuyển sang đường dự phòng) chỉ nhận mã lỗi hết hạn mức, hoặc câu thông báo chuẩn của dịch vụ trong sự kiện lỗi Codex. Văn bản trong câu trả lời/tool output (kết quả công cụ), lỗi mạng hoặc HTTP 429 chung không kích hoạt chuyển model. Nếu phiên bản CLI trả lỗi khác định dạng đã biết, chương trình dừng để kiểm tra thay vì đoán.

```sh
python3 -m unittest discover -s automation/tests -v
```

Các kiểm thử tự động dùng repo và bare remote (repo Git chỉ lưu lịch sử) tạm trên máy. Chúng không gọi ChatGPT/AGY thật hoặc sử dụng hạn mức. Kết quả chạy AGY thật và giới hạn cầu nối được ghi riêng trong `VALIDATION.md`.
