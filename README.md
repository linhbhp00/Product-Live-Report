# Product Live Report — Streamlit

Streamlit MVP để upload Order Report theo ngày, map ASIN với Product Master từ Lark Base và phân tích sale theo thời gian.

## Chạy local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Dữ liệu đầu vào

- **Product Master:** ASIN, SKU, Product Name, Product Type, ASIN Manager/Product Owner, MRnD, Listing By, Custom By, Status.
- **Order Report:** Order Date, Order ID, ASIN, Qty, Item Price, Shipping, Promotion.

Hỗ trợ `.csv`, `.xlsx` và `.xls`. Promotion nên là số âm nếu là khoản giảm giá.

## Deploy trên Streamlit Community Cloud

Chọn repository này và đặt **Main file path** là `streamlit_app/app.py`.
