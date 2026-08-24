# Product Live Report — Streamlit

Streamlit MVP để upload Order Report theo ngày, map ASIN với Product Master từ bảng `TOTAL ASINs` / view `All` trên Lark Base và phân tích sale theo thời gian. Nếu không có quyền Lark API, có thể upload trực tiếp file export của Base.

## Chạy local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Dữ liệu đầu vào

- **Product Master:** export [TOTAL ASINs / All](https://everlastify.jp.larksuite.com/base/RXnkbQ0NXaPKanshOEfjtNwjp7k?table=tblgsIV71tjUvLlB&view=vewuAjvYoo) thành `.xlsx`/`.csv`, hoặc đồng bộ bằng API.
- Mapping: `ASIN`, `Record ID`, `Image`, `AMZ SKU → SKU`, `Product Name`, `Product Type`, `AMZ Store → Store`, `Managed By/Owners → ASIN Manager`, `MRnD Idea → MRnD`, `Fulfill By`, `Listing By`, `Custom By`, `Status`.
- Cột `Image` được hiển thị trực tiếp trong bảng khi Product Master cung cấp URL ảnh (`http`, `https` hoặc data URI). File Excel chỉ chứa tên ảnh nhưng không kèm URL sẽ để trống ảnh để tránh biểu tượng lỗi.
- **Order Report:** hỗ trợ trực tiếp file `.txt` tab-delimited của Amazon cùng `.tsv`, `.csv`, `.xlsx`, `.xls`.

`Purchase Time` được giữ timezone-aware và chuyển tuần tự từ UTC sang `America/Los_Angeles`, sau đó sang `Asia/Ho_Chi_Minh` trước khi lọc ngày và group tuần. `Revenue = Item Price + Shipping Price`. App tự loại `Cancelled/Canceled`, các order có `fulfillment-channel = Amazon` và ASIN có `Fulfill By = FBA`; chỉ giữ FBM.

Dashboard có bộ lọc Store và biểu đồ donut hai tầng: vòng ngoài là MRnD/Non-MRnD, vòng trong chia Wrappiness (`WR`) và Pawsionate (`PAW`) trong từng nhóm. Tỷ trọng phần trăm xuất hiện trên lát đủ lớn, trong tooltip và trong chú giải. Bốn KPI Revenue, Orders, ASIN Sold và Total ASIN được bố trí 2×2 bên phải biểu đồ.

## Deploy trên Streamlit Community Cloud

Chọn repository này và đặt **Main file path** là `app.py`.

Trong **Advanced settings → Secrets**, thêm:

```toml
[lark]
app_id = "cli_xxx"
app_secret = "xxx"

[amazon]
access_token = "Amazon Creators API access token"
partner_tag = "your-associate-tag"
marketplace = "www.amazon.com"

[admin]
# Khuyến nghị dùng SHA-256 thay cho plaintext.
password_sha256 = "sha256-cua-mat-khau-creator"

[database]
# PostgreSQL/Supabase connection string. Bắt buộc trên production để Order Report persist qua restart.
url = "postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require"
```

Không lưu secret vào GitHub. Lark custom app cần quyền đọc Base và phải được cấp quyền truy cập bảng `TOTAL ASINs`. Amazon Creators API là tùy chọn, dùng để tự điền ảnh chính thức theo ASIN; nếu không cấu hình, app vẫn dùng URL ảnh có sẵn trong Product Master.

## Quyền và persistence

- Viewer chỉ xem dashboard; phần upload, xóa và import history chỉ xuất hiện sau khi creator đăng nhập.
- Một lần import có thể chọn nhiều Order Report. Các dòng được deduplicate bằng hash và append thành một batch đã khóa.
- Creator có thể xóa trọn một batch sau bước xác nhận; app không overwrite dữ liệu cũ.
- Nếu thiếu `database.url`, app dùng SQLite local để phát triển và hiển thị cảnh báo. Streamlit Community Cloud không bảo đảm giữ file local sau restart, vì vậy production phải cấu hình PostgreSQL/Supabase.

Product Master cần thêm cột `Custom Check Done` để bật Listings Performance, KPI ASIN mới và Sold Rate. Cột này hỗ trợ timestamp Lark (epoch milliseconds) hoặc chuỗi ngày/giờ.

