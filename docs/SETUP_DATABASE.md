# Hướng dẫn cài đặt Database sau khi clone dự án

Tài liệu này hướng dẫn developer dựng lại **PostgreSQL database** từ code của dự án, **không cần xin file dump**.

---

## 1) Cài đặt PostgreSQL

Cài PostgreSQL trên máy (nếu chưa có).

Kiểm tra:

```bash
psql --version
```
psql (PostgreSQL) 18.1

---
## 2) Tạo database rỗng

Đăng nhập PostgreSQL:
```sql
CREATE DATABASE standards_ai
WITH 
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.utf8'
    LC_CTYPE = 'en_US.utf8'
    TEMPLATE = template0;

```
---
## 3) Tạo file môi trường .env

Tại thư mục root của project, tạo file:
```
.env
```
Nội dung:
```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=standards_ai
DB_USER=postgres
DB_PASSWORD=your_password
```
Tham khảo file .env.example 

## 4) Cài thư viện Python
```bash
pip install -r requirements.txt
```

Đảm bảo có các thư viện:

sqlalchemy
psycopg2-binary
python-dotenv

---
## 5) Tạo schema database từ models
Chạy lệnh sau tại root project:
```bash
python -m src.db.init_db
```

Nếu thành công, bạn sẽ thấy:
```bash
Database schema created.
```

Tất cả tables đã được tạo theo models.py.

---
## 6) (Tuỳ chọn) Nạp dữ liệu mẫu

Nếu project có file:
```
src/db/seed/seed_data.sql
```

Chạy:
```bash
psql -U postgres -d standards_ai -f src/db/seed/seed_data.sql
```
---

## 7) Kiểm tra

Đăng nhập lại PostgreSQL:
```bash
psql -U postgres -d standards_ai
```

Bạn sẽ thấy danh sách các bảng.

---
## Nguyên tắc quan trọng
Không dùng chung database với người khác
Không commit file .env
Khi models.py thay đổi → chỉ cần chạy lại bước 5
