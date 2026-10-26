# db/orm.py

from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import sessionmaker
from db.session import engine

Base = automap_base()

# Reflect toàn bộ schema hiện có
Base.prepare(autoload_with=engine)

SessionLocal = sessionmaker(bind=engine)

# Map table → class đặt tên rõ nghĩa
Organizations = Base.classes.organizations
Standards = Base.classes.standards
StandardIdentifiers = Base.classes.standard_identifiers
StandardEquivalents = Base.classes.standard_equivalents
StandardAliases = Base.classes.standard_aliases
StandardDocuments = Base.classes.standard_documents
StandardVersions = Base.classes.standard_versions
Categories = Base.classes.categories
StandardCategories = Base.classes.standard_categories
CategoryStandardListing = Base.classes.category_standard_listing

