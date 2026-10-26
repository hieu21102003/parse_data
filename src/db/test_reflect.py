from db.orm import SessionLocal, Standards

session = SessionLocal()

from db.orm import Base
print(Base.classes.keys())

count = session.query(Standards).count()
print("Total standards rows:", count)

std = session.query(Standards).first()

if std:
    print("STD ID:", std.std_id)
    print("RAW CODE:", std.raw_code)
else:
    print("Table standards is empty.")