# Product Live Report — Streamlit

Streamlit MVP để upload Order Report theo ngày, map ASIN với Product Master từ bảng `TOTAL ASINs` / view `All` trên Lark Base và phân tích sale theo thời gian. Nếu không có quyền Lark API, có thể upload trực tiếp file export của Base.

## Chạy local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Dữ liệu đầu vào

- **Product Master:** export [TOTAL ASINs / All](https://everlastify.jp.larksuite.com/base/RXnkbQ0NXaPKanshOEfjtNwjp7k?table=tblgsIV71tjUvLlB&view=vewuAjvYoo) thành `.xlsx`/`.csv`, hoặc đồng bộ bằng API.
- Mapping: `ASIN`, `AMZ SKU → SKU`, `Product Name`, `Product Type`, `Managed By/Owners → ASIN Manager`, `MRnD Idea → MRnD`, `Listing By`, `Custom By`, `Status`.
- **Order Report:** hỗ trợ trực tiếp file `.txt` tab-delimited của Amazon cùng `.tsv`, `.csv`, `.xlsx`, `.xls`.

`Net Revenue = Item Price + Shipping Price - Item Promotion Discount - Ship Promotion Discount`. App tự loại đơn `Cancelled`.

## Deploy trên Streamlit Community Cloud

Chọn repository này và đặt **Main file path** là `app.py`.

Trong **Advanced settings → Secrets**, thêm:

```toml
[lark]
app_id = "cli_xxx"
app_secret = "xxx"
```

Không lưu `app_secret` vào GitHub. Lark custom app cần quyền đọc Base và phải được cấp quyền truy cập bảng `TOTAL ASINs`.
