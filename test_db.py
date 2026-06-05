import pyodbc

conn = pyodbc.connect(
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=77.81.191.141,36773;"
    "DATABASE=777AiReport;"
    "UID=DBTester;"
    "PWD=Lmno@753;"
    "TrustServerCertificate=yes;"
)

cursor = conn.cursor()

cursor.execute("""
SELECT TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
""")

for row in cursor.fetchall():
    print(row)

conn.close()