# Standards_AI

AI Chatbot tra cứu **Tiêu chuẩn – Quy chuẩn – Văn bản pháp lý** bằng công nghệ **RAG (Retrieval-Augmented Generation)** và **Vector Embedding**.

Mục tiêu của dự án là xây dựng một hệ thống cho phép người dùng hỏi bằng ngôn ngữ tự nhiên và nhận được câu trả lời **chính xác theo điều khoản tiêu chuẩn**, kèm trích dẫn nguồn.

---
## Tính năng chính

- Import tiêu chuẩn từ PDF/Word
- Tự động cắt đoạn (chunking) và tạo embedding
- Lưu trữ vào Vector Database để truy vấn ngữ nghĩa
- Chatbot hỏi đáp theo tiêu chuẩn
- Lưu trữ metadata tiêu chuẩn bằng ORM/SQL
- Kiến trúc sẵn sàng mở rộng cho nhiều bộ tiêu chuẩn

---

## Kiến trúc tổng thể
PDF Standards
↓
Ingestion Pipeline (chunk → embedding)
↓
Vector Store
↓
RAG Retriever
↓
LLM + Prompt
↓
Chatbot API

## 📁 Cấu trúc thư mục
```text
standards_ai/
│
├─ src/ # Toàn bộ source code
│ ├─ app/ # API / chatbot
│ ├─ ingestion/ # Import và xử lý tiêu chuẩn
│ ├─ rag/ # Logic truy vấn vector + prompt
│ ├─ vector_store/ # Code thao tác vector DB
│ ├─ prompts/ # Prompt template
│ └─ db/ # ORM, models, session
│
├─ data/ # PDF tiêu chuẩn gốc (không commit)
├─ vector_store_data/ # Index sinh ra (không commit)
├─ tests/
├─ docs/
│
├─ .env
├─ requirements.txt
├─ docker-compose.yml
└─ README.md
```

---

## ⚙️ Nguyên tắc quan trọng

| Thư mục | Nội dung | Commit git |
|---|---|---|
| `src/` | Code Python | ✅ |
| `data/` | PDF tiêu chuẩn | ❌ |
| `vector_store_data/` | FAISS/Chroma index | ❌ |

---

## 🛠️ Quy trình hoạt động

1. Đặt file tiêu chuẩn vào `data/`
2. Chạy module `ingestion` để:
   - Cắt đoạn văn bản
   - Tạo embedding
   - Lưu vào vector store
3. Khởi chạy API chatbot
4. Người dùng hỏi → hệ thống truy vấn vector → LLM trả lời có trích dẫn

---

## ▶️ Chạy dự án (local)

```bash
pip install -r requirements.txt
docker-compose up
```

## 🔐 Bảo mật dữ liệu
- Không commit dữ liệu tiêu chuẩn
- Không commit vector index
- Sử dụng .env cho cấu hình nhạy cảm

## 📌 Định hướng mở rộng
- Hỗ trợ nhiều bộ tiêu chuẩn khác nhau
- Thêm giao diện web
- Triển khai nội bộ qua Docker/Kubernetes
- Kết nối với hệ thống quản lý văn bản pháp lý

## 👥 Đối tượng sử dụng
- Kỹ sư thiết kế
- Tư vấn giám sát
- Pháp chế kỹ thuật
- Quản lý dự án hạ tầng

## 📄 License
Nội bộ / Private project.


PYTHONPATH=src python -m pipeline  "C:\Users\hyeu pc\Downloads\2. Thống kê Các tiêu chuẩn Nước ngoài Tổng hợp.xlsx" -o ket_qua.xlsx
PYTHONPATH=src python -m pipeline sample.pdf sample.xlsx -o out.json
PYTHONPATH=src python -m pipeline --text "TCVN 1234:2020"
 python -m pipeline --text "TCVN 13695-1 đến 10:2023 (BS EN 13146-1 đến 10:2019)" -o /tmp/ket_qua.xlsx
 "C:\Users\hyeu pc\Downloads\2. Thống kê Các tiêu chuẩn Nước ngoài Tổng hợp.xlsx"
 • Chạy pipeline qua CLI:                                                                                                                                              
    python -m src.pipeline sample.pdf -o out.json                                                                                                                       
    python -m src.pipeline --text "TCVN 1234:2020" -o ket_qua.xlsx                                                                                                      
                                                                                                                                                                        
  • Chạy Web API & UI:                                                                                                                                                  .venv\Scripts\activate.bat
    uvicorn src.app.main:app --reload --port 8000 