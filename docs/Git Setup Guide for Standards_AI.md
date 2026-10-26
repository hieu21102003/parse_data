# Git Setup Guide for Standards_AI

Tài liệu này hướng dẫn khởi tạo và cấu hình Git cho dự án sau khi phần source code và DB đã sẵn sàng.

---

## 1) Cài đặt Git

Kiểm tra Git đã có trên máy:
```bash
git --version
```

## 2) Khởi tạo Git trong thư mục dự án
Di chuyển tới thư mục gốc của dự án:
```
cd D:\work\standards_ai
```
Khởi tạo repository:
```
git init
```
## 3) Tạo file .gitignore
(nếu chưa có)

```gitignore
# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.venv/
env/

# Environment variables
.env

# IDE
.idea/
.vscode/

# Data & vector store
data/
vector_store_data/

# Logs
*.log

# OS
.DS_Store
Thumbs.db
```

---

## 4) Kiểm tra trạng thái
```
git status
```
Đảm bảo KHÔNG thấy:

- .env
- data/
- vector_store_data/
- .venv/

---

## 5) Commit lần đầu
```
git add .
git commit -m "Initial project structure with DB architecture and RAG skeleton"
```
---

## 6) Tạo repository trên Git server
Tạo repo tạo repo tên standards_ai rỗng trên một trong các nền tảng:

- GitHub
- GitLab
- Bitbucket

---
## 7) Kết nối local repo với remote
Sao chép URL repo, ví dụ:
```
https://github.com/phantrunglam/standards_ai.git
```
Thực hiện:
```
git remote add origin https://github.com/your_org/standards_ai.git
git branch -M main
git push -u origin main
```
---

## 8) Quy ước làm việc nhóm (khuyến nghị)
Mỗi dev khi clone về sẽ:
```
git clone <repo_url>
cd standards_ai
python -m venv .venv
pip install -r requirements.txt
```
Sau đó tự tạo DB bằng:
```
python src/db/init_db.py
```
---
## 9) Quy tắc commit

Nên commit theo nhóm chức năng:
```
git commit -m "feat: add document ingestion pipeline"
git commit -m "fix: session engine config"
git commit -m "refactor: db models split"
```
---
## 10) Kiểm tra remote
```
git remote -v
```

