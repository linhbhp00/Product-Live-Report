# Product Live Report — Streamlit

Streamlit MVP để upload Order Report theo ngày, map ASIN với **một Product Master duy nhất** là bảng `TOTAL ASINs` / view `All` trên Lark Base và phân tích sale theo thời gian.

## Chạy local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Dữ liệu đầu vào

- **Product Master cố định:** [TOTAL ASINs / All](https://everlastify.jp.larksuite.com/base/RXnkbQ0NXaPKanshOEfjtNwjp7k?table=tblgsIV71tjUvLlB&view=vewuAjvYoo).
- Mapping: `ASIN`, `AMZ SKU → SKU`, `Product Name`, `Product Type`, `Owners → ASIN Manager`, `MRnD Idea → MRnD`, `Listing By`, `Custom By`, `Status`.
- **Order Report:** Order Date, Order ID, ASIN, Qty, Item Price, Shipping, Promotion.

Hỗ trợ `.csv`, `.xlsx` và `.xls`. Promotion nên là số âm nếu là khoản giảm giá.

## Deploy trên Streamlit Community Cloud

Chọn repository này và đặt **Main file path** là `app.py`.

Trong **Advanced settings → Secrets**, thêm:

```toml
[lark]
app_id = "cli_xxx"
app_secret = "xxx"
```

Không lưu `app_secret` vào GitHub. Lark custom app cần quyền đọc Base và phải được cấp quyền truy cập bảng `TOTAL ASINs`.
