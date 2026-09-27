# Repo mẫu thử vòng review và sửa

Đây là dữ liệu thử nghiệm độc lập, không chứa mã của repo thật.

`paginate(items, page, per_page)` phải:

- Nhận `page` và `per_page` là số nguyên dương, loại trừ `bool`.
- Dùng số trang bắt đầu từ 1.
- Trả về một danh sách mới chứa đúng phần tử của trang, giữ nguyên dữ liệu đầu vào.
- Trả danh sách rỗng khi đầu vào rỗng hoặc trang vượt dữ liệu.
- Ném `ValueError` nếu tham số trang không hợp lệ.

Bản khởi đầu cố ý có lỗi để kiểm chứng khả năng phát hiện của reviewer (tác nhân rà soát). Chạy `python3 -m unittest -v` trước và sau khi sửa để đối chiếu.

