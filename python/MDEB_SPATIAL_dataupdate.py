###############################################################################
## This script updates AGOL feature service data. It pulls data from the     ##
## oracle database and creates a pandas dataframe. It then deletes old data  ##
## from the feature service and loads the new data.                          ##
###############################################################################

# IMPORT LIBRARIES
from dotenv import load_dotenv
import os
import pandas as pd
import oracledb
from sqlalchemy import create_engine, text
from arcgis.gis import GIS
from arcgis.geometry import Geometry
from shapely.wkt import loads as wkt_loads

# AUTHENTICATE ARCGIS CREDENTIALS
# Using ArcGIS Pro to authenticate, change authentication scheme if necessary
gis = GIS("PRO")

# CONNECT TO ORACLE
# Enable thick mode, using oracle instant client and tnsnames.ora
oracledb.init_oracle_client()

# Access .env variables
load_dotenv(dotenv_path = os.path.expandvars(r"%USERPROFILE%\.config\secrets\.env"))
tns_name = os.getenv("TNS_NAME") 
username = os.getenv("ORACLE_USERNAME")
password = os.getenv("ORACLE_PASSWORD") 
schema = os.getenv("SCHEMA")
lyr_table = os.getenv("LYR_TABLE")
fld_table = os.getenv("FLD_TABLE")

# Connect to oracle database using SQL alchemy engine and TNS names alias
connection_string = f"oracle+oracledb://{username}:{password}@{tns_name}"
engine = create_engine(connection_string)
connection = engine.connect()

# DATA EXTRACTION FROM THE DATABASE
# Query table to get AGOL layer info (layer name, url, and layer id)
layers_sql_query = f"SELECT * FROM {schema}.{lyr_table}"
df_layers = pd.read_sql(layers_sql_query, con = connection)

# Query table to get field info within tables
fields_sql_query = f"SELECT * FROM {schema}.{fld_table}"
df_fields = pd.read_sql(fields_sql_query, con = connection)

# Now extract all spatial tables from oracle
# Create an empty dictionary to hold all dataframes
dataframes = {}

# Get the list of table names from df_fields
table_names = df_fields['table_name'].unique()
print("Getting tables from the database...")

# Make a separate pandas dataframe for each spatial table in the database
# Ensure that geometry column is handled correctly (convert to wkt)
with engine.connect() as connection:
    for table_name in table_names:
        try:
            print(f"--- Processing table: '{table_name}' ---")

            columns = df_fields[df_fields['table_name'] == table_name]['col_name'].tolist()

            # Join the known column names into a single string
            columns_sql_str = ", ".join(columns)

            # Build the final SELECT statement
            # Manually add the SDO_GEOM conversion for the 'shape' column to every query
            final_columns_str = f"{columns_sql_str}, TBL.SHAPE.SDO_SRID as SHAPE_SRID, SDO_UTIL.TO_WKTGEOMETRY(SHAPE) AS SHAPE_WKT"

            # Construct the final SQL query
            query = text(f'SELECT {final_columns_str} FROM {schema}.{table_name} TBL')

            # Execute the query and store the resulting DataFram
            df = pd.read_sql_query(query, con = connection)
            if df.shape_srid.all() != True:
                warnings.warn(f"SHAPE column in the DataFrame contains multiple SRID values.")
            dataframes[table_name] = df
            print(f"  Successfully loaded '{table_name}'")

        except Exception as e:
            print(f" FAILED to load table '{table_name}': {e}")

 # Make all dataframes and columns in dataframes uppercase
 # This is how everything is named in AGOL
upper_dataframes = {
    key.upper(): df.rename(columns = str.upper) 
    for key, df in dataframes.items()
}
print("Converted all data table names and columns to uppercase.")

# DATA UPDATE LOOP
# Loop through each row in df_layers to update a feature layer on AGOL using pandas dataframe
# Make sure to correctly handle geometry (use shapely and create spatially enabled dataframe)
for index, layer_row in df_layers.iterrows():
    try:
        item_id = layer_row['file_id']
        rest_url = layer_row['rest_url']
        table_name = layer_row['table_name'] # The key to retrieve the data frame from the dictionary
        
        # Get the WKID for the hosted feature service layer, use this to set the spatial ref for the sedf
        feature_layer_item = gis.content.get(item_id)
        layer_index = int(rest_url[len(rest_url) - 1])
        target_layer = feature_layer_item.layers[layer_index]
        spatial_ref_info = target_layer.properties.spatialReference
        wkid = spatial_ref_info['wkid']
        latest_wkid = spatial_ref_info.get('latestWkid', wkid)
        
        print(f"--- Processing Layer: '{table_name}' ---")

        # Get DataFrame for this layer
        source_df = upper_dataframes.get(table_name)
        if source_df is None or source_df.empty:
            print(f"  - No data found for table '{table_name}'. Skipping.")
            continue

        # Create spatially enabled dataframe
        print("  - Converting WKT to geometry using Shapely...")
        sedf = source_df.copy()

        # Get SRID for Oracle data
        oracle_srid = sedf.SHAPE_SRID.unique()[0]
        
        # For each WKT string, load it with Shapely, get its standard geo_interface,
        # and create an arcgis.geometry.Geometry object from that
        # Use Oracle SRID to set spatial reference
        sedf['SHAPE'] = sedf['SHAPE_WKT'].apply(
            lambda wkt: Geometry(
            wkt_loads(wkt).__geo_interface__,
            spatial_reference={'wkid': oracle_srid}
            )
        )
        
        # Drop well known text column
        sedf.drop('SHAPE_WKT', axis = 1, inplace = True)
        
        # Project to wkid of AGOL feature layer
        sedf.spatial.project(latest_wkid)

        # Access the FeatureLayer object from AGOL
        # Get a count of features
        feature_count = target_layer.query(return_count_only = True)
        print(f"Checking layer... Found {feature_count} features.")

        # Delete data in layer
        if feature_count > 0:
            print("  - Deleting existing features...")
            delete_result = target_layer.delete_features(where = '1=1')
            print("Successfully deleted features.")
        
        else:
            print("Layer is already empty. No features to delete.")
        
        # Add the new features from Spatially Enabled DataFrame
        print(f"  - Adding {len(sedf)} new features...")
        add_result = target_layer.edit_features(adds = sedf)

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
