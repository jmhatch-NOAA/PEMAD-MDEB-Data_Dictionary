###############################################################################
## This script updates AGOL feature service data. It pulls data from the     ##
## oracle database and creates a pandas dataframe. It then deletes old data  ##
## from the feature service and loads the new data.                          ##
###############################################################################

#IMPORT LIBRARIES
from dotenv import load_dotenv
import os
import pandas as pd
import oracledb
from sqlalchemy import create_engine, inspect, text
from arcgis.gis import GIS
from arcgis.geometry import Geometry
from shapely.wkt import loads as wkt_loads

#AUTHENTICATE ARCGIS CREDENTIALS
#using ArcGIS Pro to authenticate, change authentication scheme if necessary
gis = GIS("PRO")

#CONNECT TO ORACLE
#Enable thick mode, using oracle instant client and tnsnames.ora
oracledb.init_oracle_client()

#Access .env variables
load_dotenv(dotenv_path=os.path.expandvars(r"%USERPROFILE%\.config\secrets\.env"))
tns_name = os.getenv("TNS_NAME_DEV") 
username = os.getenv("USERNAME_DEV")
password = os.getenv("PASSWORD_DEV") 

#Connect to oracle database using SQL alchemy engine and TNS names alias
connection_string = f"oracle+oracledb://{username}:{password}@{tns_name}"
engine = create_engine(connection_string)
connection= engine.connect()
inspector = inspect(engine)

#SET VARIABLES
# Set the spatial reference (WKID) of dataframes and the schema name
#AGOL needs a projected coordinate system to calculate Shape_Length and Shape_Area
spatial_ref_WKID = 3857      #web mercator is standard for AGOL hosted feature services
SCHEMA = 'MDEB_SPATIAL'

#DATA EXTRACTION FROM THE DATABASE
# query smit_meta_layers to get AGOL layer info (layer name, url, and layer id)
layers_sql_query = "SELECT table_name, strata_short, rest_url, file_id FROM mdeb_spatial.smit_meta_layers"
df_layers = pd.read_sql(layers_sql_query, con = connection)

#now extract all spatial tables from oracle
# Create an empty dictionary to hold all dataframes
dataframes = {}

# Get the list of table names from df_layers
table_names = df_layers['table_name'].tolist()
table_names = [name.lower() for name in table_names]
print("Getting tables from the database...")

#make a separate pandas dataframe for each spatial table in the database
#ensure that geometry column is handled correctly (convert to wkt)
with engine.connect() as connection:
    for table_name in table_names:
        try:
            print(f"--- Processing table: '{table_name}' ---")
            
            columns = inspector.get_columns(table_name, schema= SCHEMA)

            #create the SQL query to correctly extract all columns, including geometry column
            column_select_list = []
            for col in columns:
                # Use quotes around column names for robustness
                col_name = f'"{col["name"].upper()}"' 
                
                if col['name'].upper() == 'SHAPE': 
                    # convert SDO_GEOM to WKT 
                    column_select_list.append(f"sdo_util.to_wktgeometry({col_name}) AS shape_wkt")
                else:
                    column_select_list.append(col_name)
            
            column_str = ", ".join(column_select_list)
            
            sql_query = f'SELECT {column_str} FROM "{SCHEMA}"."{table_name.upper()}"'
            
            print(f"  Executing SQL: {sql_query}")
            
            df = pd.read_sql_query(text(sql_query), connection)
            dataframes[table_name] = df
            print(f"  Successfully loaded '{table_name}'")

        except Exception as e:
            print(f"  FAILED to load table '{table_name}': {e}")

#make all dataframes and columns in dataframes uppercase
#this is how everything is named in AGOL
upper_dataframes = {
    key.upper(): df.rename(columns=str.upper) 
    for key, df in dataframes.items()
}
print("Converted all data table names and columns to uppercase.")

#DATA UPDATE LOOP
# Loop through each row in df_layers to update a feature layer on AGOL us pandas dataframe
# make sure to correctly handle geometry (use shapely and create spatially enabled dataframe)
for index, layer_row in df_layers.iterrows():
    try:
        item_id = layer_row['file_id']
        rest_url = layer_row['rest_url']
        table_name = layer_row['table_name'] # The key to retrieve the data frame from the dictionary
        
        print(f"--- Processing Layer: '{table_name}' ---")

        #get DataFrame for this layer
        source_df = upper_dataframes.get(table_name)
        if source_df is None or source_df.empty:
            print(f"  - No data found for table '{table_name}'. Skipping.")
            continue

        #create spatially enabled dataframe
        print("  - Converting WKT to geometry using Shapely...")
        sedf = source_df.copy()

        # For each WKT string, load it with Shapely, get its standard geo_interface,
        # and create an arcgis.geometry.Geometry object from that.
        # include the spatial reference
        sedf['SHAPE'] = sedf['SHAPE_WKT'].apply(
            lambda wkt: Geometry({
                **wkt_loads(wkt).__geo_interface__
            })
        )

        #drop well known text column
        sedf.drop('SHAPE_WKT', axis=1, inplace=True)

        #project into the projected coordinate system
        #this is so AGOL can calculate Shape_Length and Shape_Area
        sedf_proj=sedf.spatial.project(spatial_ref_WKID )

        #Get the FeatureLayer object from AGOL
        feature_layer_item = gis.content.get(item_id)
        layer_index = int(rest_url.strip('/').split('/')[-1])
        target_layer = feature_layer_item.layers[layer_index]

        #delete data in layer
        print("  - Deleting existing features...")
        delete_result = target_layer.delete_features(where='1=1')

        # #check that data delete was successful
        if delete_result['deleteResults']:
             print("Successfully deleted features.")
        else:
            print("Failed to delete features. Aborting for this layer.")
            continue 
        
        #Add the new features from Spatially Enabled DataFrame
        print(f"  - Adding {len(sedf)} new features...")
        add_result = target_layer.edit_features(adds=sedf)

        # Check if the add operation was successful
        add_errors = [res for res in add_result['addResults'] if not res['success']]
        if not add_errors:
            print(f"  - Successfully added new features to '{table_name}'.\n")
        else:
            print("Failed to add some or all features.")
            print(f"Errors: {add_errors}\n")

    except Exception as e:
        print(f"An unhandled error occurred for layer '{layer_row.get('layer_name', 'N/A')}': {e}\n")

print("Script finished. All AGOL feature layer data was updated.")