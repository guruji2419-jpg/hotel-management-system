import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import get_connection

conn1 = get_connection()
cur1 = conn1.cursor()
cur1.execute("INSERT INTO services (service_name, category, unit_price) VALUES (?, ?, ?)", ("TEST_MUTATION", "Test", 10.0))
conn1.commit()
conn1.close()

conn2 = get_connection()
cur2 = conn2.cursor()
cur2.execute("SELECT * FROM services WHERE service_name = ?", ("TEST_MUTATION",))
row = cur2.fetchone()
print("Persisted row found:", dict(row) if row else None)
assert row is not None, "Row was not persisted!"

cur2.execute("DELETE FROM services WHERE service_name = ?", ("TEST_MUTATION",))
conn2.commit()
conn2.close()

print("Commit persistence test PASSED successfully!")
