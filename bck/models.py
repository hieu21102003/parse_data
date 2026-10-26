# db/models.py

from sqlalchemy import (
    Column, Integer, String, ForeignKey, Text, DateTime
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    code = Column(String(50))          # II, II.1, Sub 1
    name_vi = Column(String(255))
    name_en = Column(String(255))
    level = Column(Integer)            # 1,2,3
    parent_id = Column(Integer, ForeignKey("categories.id"))

    parent = relationship("Category", remote_side=[id])
    standards = relationship("Standard", back_populates="category")


class Standard(Base):
    __tablename__ = "standards"

    id = Column(Integer, primary_key=True)

    # Chuỗi gốc từ Word/PDF
    raw_code = Column(String(256), nullable=False)

    # Parsed fields
    org_code = Column(String(50))          # IEC, EN, TCVN, IEEE, AASHTO...
    std_number = Column(String(100))      # 62368-1, 802.11...
    version_text = Column(String(100))    # Version 2, Rel-18, 2nd edition
    year = Column(Integer)

    title = Column(Text)

    category_id = Column(Integer, ForeignKey("categories.id"))
    category = relationship("Category", back_populates="standards")

    created_at = Column(DateTime, default=datetime.utcnow)


class StandardAmendment(Base):
    __tablename__ = "standard_amendments"

    id = Column(Integer, primary_key=True)

    standard_id = Column(Integer, ForeignKey("standards.id"))
    amend_type = Column(String(20))   # AMD, AC, ERRATA, I1, A1...
    amend_year = Column(Integer)

    standard = relationship("Standard")
