#This script is to connect to Oracle database, query data and metadata to make feature layers
#Then, publish data to arcgis.com
#Script will be automated in the future to update feature layers

#Used to add EcoMon data, metadata from oracle to arcgis.com

#IMPORT LIBRARIES
import json
import pandas as pd
import geopandas
import geopandas as gpd
import shapely
import xml.etree.ElementTree as ET
from shapely import wkt
import arcpy, arcgis, requests, os, sys, shutil
import sqlalchemy
from sqlalchemy import create_engine, select, MetaData, Table
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import create_engine
from arcgis.gis import GIS
from arcgis import features as fs
from arcgis.geometry import Geometry
from arcgis.features import FeatureLayer, FeatureLayerCollection, FeatureCollection, GeoAccessor, GeoSeriesAccessor
from arcgis.features.managers import FeatureLayerCollectionManager

#CHANGE VARIABLES
#variables to change based on layer that is being published (change these when making new script)
#EcoMon Strata
strata_table = 'ECOMONSTRATA' #choose strata table that you would like to make into feature layer, choose table name from oracle db
query = f"SELECT SDO_UTIL.TO_WKTGEOMETRY(SHAPE) AS geometry_wkt, name, survey_name, numofpoly, numofsta, region, area, type, acres, version_date FROM {strata_table}" #SQL query of data to pull from oracle db
shp_folder = "EcoMon_strata" #name of folder that will be created to hold shapefile data
zip_folder = "Ecosystem Monitoring Strata" #name of zipfolder

#do this for multiple layers if you want a feature layer collection with many layers

#CONNECT TO ORACLE
#Connect to oracle database using SQL alchemy engine
DIALECT = 'oracle'
SQL_DRIVER = 'cx_oracle'
USERNAME = '' #enter your username
PASSWORD = '' #enter your password
HOST = '' #enter the oracle db host url
PORT =  # enter the oracle port number
SERVICE = '' # enter the oracle db service name
ENGINE_PATH_WIN_AUTH = DIALECT + '+' + SQL_DRIVER + '://' + USERNAME + ':' + PASSWORD +'@' + HOST + ':' + str(PORT) + '/?service_name=' + SERVICE
engine = create_engine(ENGINE_PATH_WIN_AUTH)
connection= engine.connect()

#PREPARE DATA
#create pandas dataframe from SQL query
df = pd.read_sql_query(query, engine)
print(f"Data types of each column: {df.dtypes}")

#close database connection
connection.close()

#convert dataframe to zipped shapefile (pandas to geopandas to shapefile)
#EcoMon
df['geometry'] = gpd.GeoSeries.from_wkt(df['geometry_wkt'])
gdf = gpd.GeoDataFrame(df, geometry='geometry')
gdf=gdf.drop(columns=['geometry_wkt'])
gdf=gdf.set_crs(epsg=4269) #set coordinate system to NAD83
#convert the geodataframe to zipped shapefile folder
gdf.to_file(shp_folder, driver="ESRI Shapefile")
shutil.make_archive(zip_folder, "zip", shp_folder)

#PREPARE METADATA
#metadata is being pulled from table in oracle
#define the metadata table and query
metadata_table = 'STRATA_METADATA' #metdata table name in oracle
metadata = MetaData(bind=engine)
table = Table(metadata_table, metadata, autoload_with=engine)

#query the table for metadata based on the name of the scientific strata

column_name = 'strata_table_name'

value1 = strata_table

with engine.connect() as connection:
    query = select([table]).where(table.c[column_name] == value1)
    result1 = connection.execute(query).fetchone() #fetch metadata row for specified strata
    
if result1:
  print(result1.keys())
 
print('Done')  

#extract metadata values
if result1:
  title1 = result1.strata_long
  description1 = f"{result1.link}. {result1.description}"
  summary1 = result1.summary
  tags1 = result1.tags.split(',')
  credits1 = result1.owner_affiliation
  useterms1 = result1.useterms
else: 
  raise ValueError("No metadata found in SQL Table")

print('Done') 

#PUBLISH
#connect to arcgis online
#authenticates based on portal logged in through ArcGIS Pro
#need to authenticate correctly/differently if this is run on something other than my pc

gis= GIS("PRO")
if gis is not None and gis._portal.is_logged_in:
  print(f"Successfully logged in as: {gis.properties.user['username']}")
else:
  print("Login failed.")
  
shapefile_item = gis.content.add({}, 'Ecosystem Monitoring Strata.zip')
published_item = shapefile_item.publish()
feature_service_url = published_item.url

#set metadata for the feature service
dictUpdate = {
  "copyrightText": useterms1,
  "title": title1,
  "type": "Feature Collection",
  "tags":  tags1,
  "snippet" : summary1, #summary
  "serviceDescription" : description1,
  "description": description1,
  "accessInformation" : credits1,
  "objectIdField" : "FID"
}
#set metadata for the layer [0]
item_properties = {
    "title" : title1,
    "tags" : tags1,
    "snippet" : summary1, #summary
    "description" : description1,
    "licenseInfo" : useterms1, # terms of use
    "accessInformation" : credits1,
    "type" : "Shapefile",
    "categories" : "Biota, Environment, Oceans",
    "copyrightText": useterms1
}

#add/update feature service metadata
url= "https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/Ecosystem_Monitoring_Strata/FeatureServer"
feature_server = FeatureLayer(url)
feature_server.manager.update_definition(dictUpdate)

#add/update the feature layer metadata
item_id = 'b5191658ef1541638ca45227d711d734'
item = gis.content.get(item_id)
item.update(item_properties)

# MORE METADATA UPDATES

#update the field aliases in the layer to be more human readable
#pull current field data, print it, then edit it in a text document to include field aliases
#load edited text document and push to arcgis online to add field alias names
layer = item.layers[0]
fields=layer.properties.fields
print(layer.properties.fields)

with open("C:/Users/Nicole.Mucci/Documents/Notepad/field.json") as json_data:
    data = json.load(json_data)

layer.manager.update_definition(data)    

#metadata contact information was added manually via arcgis.com
#need to find a way to update metadata contact information programatically
#this will probably include downloading xml file, changing file, and then adding updated xml file 
