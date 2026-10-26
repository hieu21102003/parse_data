from typing import Optional
from src.db.base import Base
import datetime

from sqlalchemy import Date, DateTime, ForeignKeyConstraint, Index, Integer, PrimaryKeyConstraint, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# class Base(DeclarativeBase):
#     pass


class Categories(Base):
    __tablename__ = 'categories'
    __table_args__ = (
        ForeignKeyConstraint(['parent_id'], ['categories.category_id'], name='categories_parent_id_fkey'),
        PrimaryKeyConstraint('category_id', name='categories_pkey')
    )

    category_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[Optional[int]] = mapped_column(Integer)
    category_code: Mapped[Optional[str]] = mapped_column(String(50))
    category_name_vi: Mapped[Optional[str]] = mapped_column(Text)
    category_name_en: Mapped[Optional[str]] = mapped_column(Text)
    level: Mapped[Optional[int]] = mapped_column(Integer)
    sort_order: Mapped[Optional[int]] = mapped_column(Integer)

    parent: Mapped[Optional['Categories']] = relationship('Categories', remote_side=[category_id], back_populates='parent_reverse')
    parent_reverse: Mapped[list['Categories']] = relationship('Categories', remote_side=[parent_id], back_populates='parent')
    category_standard_listing: Mapped[list['CategoryStandardListing']] = relationship('CategoryStandardListing', back_populates='category')
    standard_categories: Mapped[list['StandardCategories']] = relationship('StandardCategories', back_populates='category')


class LegalDocuments(Base):
    __tablename__ = 'legal_documents'
    __table_args__ = (
        PrimaryKeyConstraint('doc_id', name='legal_documents_pkey'),
    )

    doc_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_title: Mapped[str] = mapped_column(Text, nullable=False)
    doc_number: Mapped[Optional[str]] = mapped_column(String(100))
    issuing_body: Mapped[Optional[str]] = mapped_column(String(255))
    issue_date: Mapped[Optional[datetime.date]] = mapped_column(Date)
    file_path: Mapped[Optional[str]] = mapped_column(Text)
    file_hash: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=text('now()'))

    legal_standard_references: Mapped[list['LegalStandardReferences']] = relationship('LegalStandardReferences', back_populates='doc')


class Organizations(Base):
    __tablename__ = 'organizations'
    __table_args__ = (
        PrimaryKeyConstraint('org_id', name='organizations_pkey'),
        UniqueConstraint('org_code', name='organizations_org_code_key')
    )

    org_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_code: Mapped[str] = mapped_column(String(20), nullable=False)
    org_name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[Optional[str]] = mapped_column(Text)


class StandardAliases(Base):
    __tablename__ = 'standard_aliases'
    __table_args__ = (
        PrimaryKeyConstraint('alias_id', name='standard_aliases_pkey'),
        UniqueConstraint('alias_text', name='standard_aliases_alias_text_key'),
        Index('idx_alias_text', 'alias_text')
    )

    alias_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    std_id: Mapped[Optional[int]] = mapped_column(Integer)
    alias_text: Mapped[Optional[str]] = mapped_column(String(100))


class StandardDocuments(Base):
    __tablename__ = 'standard_documents'
    __table_args__ = (
        PrimaryKeyConstraint('doc_id', name='standard_documents_pkey'),
    )

    doc_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    std_id: Mapped[Optional[int]] = mapped_column(Integer)
    file_path: Mapped[Optional[str]] = mapped_column(Text)
    file_name: Mapped[Optional[str]] = mapped_column(Text)
    file_hash: Mapped[Optional[str]] = mapped_column(Text)
    uploaded_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=text('now()'))


class StandardEquivalents(Base):
    __tablename__ = 'standard_equivalents'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='standard_equivalents_pkey'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    std_id: Mapped[Optional[int]] = mapped_column(Integer)
    equivalent_std_id: Mapped[Optional[int]] = mapped_column(Integer)
    note: Mapped[Optional[str]] = mapped_column(Text)


class StandardVersions(Base):
    __tablename__ = 'standard_versions'
    __table_args__ = (
        PrimaryKeyConstraint('version_id', name='standard_versions_pkey'),
    )

    version_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    std_id: Mapped[Optional[int]] = mapped_column(Integer)
    version_year: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[Optional[str]] = mapped_column(String(20))
    note: Mapped[Optional[str]] = mapped_column(Text)


class Standards(Base):
    __tablename__ = 'standards'
    __table_args__ = (
        PrimaryKeyConstraint('std_id', name='standards_pkey'),
    )

    std_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_code: Mapped[str] = mapped_column(String(256), nullable=False)
    org_prefix: Mapped[Optional[str]] = mapped_column(String(100))
    std_main_number: Mapped[Optional[str]] = mapped_column(String(100))
    std_part: Mapped[Optional[str]] = mapped_column(String(100))
    std_year: Mapped[Optional[int]] = mapped_column(Integer)
    amendment: Mapped[Optional[str]] = mapped_column(Text)
    version_text: Mapped[Optional[str]] = mapped_column(Text)
    title: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(String(20))
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=text('now()'))

    legal_standard_references: Mapped[list['LegalStandardReferences']] = relationship('LegalStandardReferences', back_populates='std')
    standard_identifiers: Mapped[list['StandardIdentifiers']] = relationship('StandardIdentifiers', back_populates='std')


class CategoryStandardListing(Base):
    __tablename__ = 'category_standard_listing'
    __table_args__ = (
        ForeignKeyConstraint(['category_id'], ['categories.category_id'], name='category_standard_listing_category_id_fkey'),
        PrimaryKeyConstraint('id', name='category_standard_listing_pkey')
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[Optional[int]] = mapped_column(Integer)
    std_id: Mapped[Optional[int]] = mapped_column(Integer)
    listing_order: Mapped[Optional[int]] = mapped_column(Integer)

    category: Mapped[Optional['Categories']] = relationship('Categories', back_populates='category_standard_listing')


class LegalStandardReferences(Base):
    __tablename__ = 'legal_standard_references'
    __table_args__ = (
        ForeignKeyConstraint(['doc_id'], ['legal_documents.doc_id'], name='legal_standard_references_doc_id_fkey'),
        ForeignKeyConstraint(['std_id'], ['standards.std_id'], name='legal_standard_references_std_id_fkey'),
        PrimaryKeyConstraint('id', name='legal_standard_references_pkey'),
        Index('idx_legal_doc', 'doc_id'),
        Index('idx_legal_std', 'std_id')
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_id: Mapped[Optional[int]] = mapped_column(Integer)
    std_id: Mapped[Optional[int]] = mapped_column(Integer)
    context_text: Mapped[Optional[str]] = mapped_column(Text)
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    obligation_level: Mapped[Optional[str]] = mapped_column(String(30))
    extracted_raw_code: Mapped[Optional[str]] = mapped_column(String(256))
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=text('now()'))

    doc: Mapped[Optional['LegalDocuments']] = relationship('LegalDocuments', back_populates='legal_standard_references')
    std: Mapped[Optional['Standards']] = relationship('Standards', back_populates='legal_standard_references')


class StandardCategories(Base):
    __tablename__ = 'standard_categories'
    __table_args__ = (
        ForeignKeyConstraint(['category_id'], ['categories.category_id'], name='standard_categories_category_id_fkey'),
        PrimaryKeyConstraint('id', name='standard_categories_pkey')
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    std_id: Mapped[Optional[int]] = mapped_column(Integer)
    category_id: Mapped[Optional[int]] = mapped_column(Integer)

    category: Mapped[Optional['Categories']] = relationship('Categories', back_populates='standard_categories')


class StandardIdentifiers(Base):
    __tablename__ = 'standard_identifiers'
    __table_args__ = (
        ForeignKeyConstraint(['std_id'], ['standards.std_id'], name='standard_identifiers_std_id_fkey'),
        PrimaryKeyConstraint('id', name='standard_identifiers_pkey')
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    std_id: Mapped[Optional[int]] = mapped_column(Integer)
    identifier_text: Mapped[Optional[str]] = mapped_column(String(256))

    std: Mapped[Optional['Standards']] = relationship('Standards', back_populates='standard_identifiers')
