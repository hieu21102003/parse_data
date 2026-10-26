from db.orm import SessionLocal, Standards

session = SessionLocal()

std = Standards(
    raw_code="IEC 62368-1:2020+AMD1:2021",
    org_prefix="IEC",
    std_main_number="62368-1",
    std_year=2020,
    amendment="AMD1:2021",
    title="Test standard"
)

session.add(std)
session.commit()

print("Inserted STD ID:", std.std_id)
