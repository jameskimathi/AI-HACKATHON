import pandas as pd
from hana_ml import ConnectionContext
from hana_ml.dataframe import create_dataframe_from_pandas

# cc = ConnectionContext(userkey='VDB_BETA', encrypt=True)
cc= ConnectionContext(
    address='<your-address>',
    port='<your-port>',
    user='<your-user>',
    password='<your-password>',
    encrypt=True
    )

print(cc.hana_version())
print(cc.get_current_schema())

# import dataset into pandas dataframe
df = pd.read_csv('dataset.csv', low_memory=False)
print(df.head(3))

# Create a table
cursor = cc.connection.cursor()
sql_command = '''CREATE TABLE PACKAGE_TRACKING("ORDER" BIGINT, "STATUS" NVARCHAR(30), "ETA" NVARCHAR(30), "POSTCODE" NVARCHAR(5));'''
cursor.execute(sql_command)
cursor.close()

# Upload csv data to table
v_hdf = create_dataframe_from_pandas(
    connection_context=cc,
    pandas_df=df,
    table_name="PACKAGE_TRACKING", 
    allow_bigint=True,
    append=True
)

# Add REAL_VECTOR column
cursor = cc.connection.cursor()
sql_command = '''ALTER TABLE PACKAGE_TRACKING ADD (VECTOR REAL_VECTOR(1536));'''
cursor.execute(sql_command)
cursor.close()

# Create vectors from strings
#cursor = cc.connection.cursor()
#sql_command = '''UPDATE PACKAGE_TRACKING SET VECTOR = TO_REAL_VECTOR(["ORDER","STATUS","ETA","POSTCODE"]);'''
#cursor.execute(sql_command)
#cursor.close()
