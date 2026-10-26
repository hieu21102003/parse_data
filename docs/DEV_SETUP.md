# Developer Setup Guide — Standards_AI

Welcome to the **Standards_AI** project.  
This guide walks you through setting up your local environment after cloning the repository so you can run the project and contribute safely.

---

## 1) Prerequisites

Install the following tools before you start:

- **Git**
- **Python 3.10+**
- **PostgreSQL 14+**

Verify:

```bash
git --version
python --version
psql --version
```
---

## 2) Clone the Repository
```
git clone <repo_url>
cd standards_ai
```
---
## 3) Create Python Virtual Environment

Always work inside a virtual environment.

#### Windows
```
python -m venv .venv
.venv\Scripts\activate
```

#### macOS, Linux
```
python -m venv .venv
source .venv/bin/activate
```
Install dependencies:
```
pip install -r requirements.txt
```
---
## 4) Create Your Local .env File (Required)
Create a file named .env at the project root:
```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=standards_ai
DB_USER=postgres
DB_PASSWORD=postgres
```
Refer .env.example

❗ This file is ignored by Git. Never commit it.
## 5) Create Database from Models

This project uses SQLAlchemy models as the single source of truth for the database schema.

You do NOT import SQL dumps.
You do NOT use pgAdmin to create tables.

Run:
```
python src/db/init_db.py
```

This will automatically create all tables in your PostgreSQL database.

---

## 6) Test Database Connection
```
python src/db/session.py
```
Expected output:
```
PostgreSQL connected:
PostgreSQL ...
```
---

## 7) Project Structure
```
src/
 ├─ app/            # API / chatbot
 ├─ ingestion/      # Import & parse standards
 ├─ rag/            # Retrieval + prompting logic
 ├─ vector_store/   # Vector DB integration
 ├─ prompts/        # Prompt templates
 └─ db/             # Database layer (models, session, init)
```
The database schema is defined in: models.py

## 8) Daily Workflow
Before coding:
```
git pull
```
After coding:
```
git add .
git commit -m "feat: short description"
git push
```
---

## 9) Rules — What You Must NOT Commit
These are intentionally ignored in .gitignore:
```
.env
.venv/
data/
vector_store_data/
Any local database files or dumps
```
## 10) If You Change Database Models
If you modify anything in models.py:

```
python src/db/init_db.py
```
Your local database will be updated accordingly.

## 11) Common Issues
Tables are not created

Make sure you ran:

python src/db/init_db.py


and your .env is correct.

Cannot connect to database

Check:
```
PostgreSQL service is running
Credentials in .env
Port 5432 is open
```
## 12) You Are Ready

At this point, your environment is fully aligned with the project architecture and you can start working on:

Ingestion pipeline
RAG logic
API endpoints
Vector store integration
