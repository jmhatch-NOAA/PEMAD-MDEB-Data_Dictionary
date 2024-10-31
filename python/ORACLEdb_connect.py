
#This code is to connect to oracle database, query spatial data in db, and create a spatial dataframe
#The spatial dataframe is then imported into an ArcGIS project for viewing 
#This code utlizes the ArcGIS API for python, refer to https://github.com/Esri/arcgis-python-api for source code
#Further documentation at https://developers.arcgis.com/python/latest/
#______________________________________________________________________

#import libraries
import pandas as pd
from shapely import wkt
import arcpy
from sqlalchemy.engine import create_engine

#create SQL alchemy engine to connect to oracle database
DIALECT = 'oracle'
SQL_DRIVER = 'cx_oracle'
USERNAME = '' #enter your username
PASSWORD = '' #enter your password
HOST = '' #enter the oracle db host url
PORT =  #enter the oracle port number
SERVICE = '' # enter the oracle db service name
ENGINE_PATH_WIN_AUTH = DIALECT + '+' + SQL_DRIVER + '://' + USERNAME + ':' + PASSWORD +'@' + HOST + ':' + str(PORT) + '/?service_name=' + SERVICE

engine = create_engine(ENGINE_PATH_WIN_AUTH)


#query spatial data in oracle db to create pandas dataframe
query = 'SELECT SDO_UTIL.TO_WKTGEOMETRY(SHAPE) AS geometry_wkt, SHAPE_LENG FROM LLSTRATA' #change query to your desired SQL query
new_df = pd.read_sql_query(query, engine) 
#SDO_UTIL.TO_WKTGEOMETRY(COLUMN_NAME) AS geometry_wkt converts a SDO spatial data column to wkt (well known text) geometry
#WKT geometry is easier to manipulate using pandas 

#close database connection 
conn.close()
#view column names and column types for dataframe
print("Data types of each column:")
print(new_df.dtypes)


#create a feature class in desired ArcGIS project
#insert project path on local computer
arcpy.management.CreateFeatureclass("C:/Users/Nicole.Mucci/Documents/ArcGIS/Projects/Database_Connect/Database_Connect.gdb", "LongLineStrata", "POLYGON", spatial_reference=4269) #change geometry type, spatial reference if necessary 
#insert project path, including name of feature class
output_featureclass = "C:/Users/Nicole.Mucci/Documents/ArcGIS/Projects/Database_Connect/Database_Connect.gdb/LongLineStrata"
#add any non-spatial columns to the feature class, add column name and column type
arcpy.AddField_management(output_featureclass, "shape_leng", "FLOAT")

#fill columns with data from dataframe via iterating through dataframe
with arcpy.da.InsertCursor(output_featureclass, ["SHAPE@", "shape_leng"]) as cursor:
  for index, row in new_df.iterrows():
    wkt = row["geometry_wkt"]
    polygon = arcpy.FromWKT(wkt)
    cursor.insertRow([polygon, row['shape_leng']])  
    
    
#feature class is now added to ArcGIS project with spatial data pulled from sQL query
