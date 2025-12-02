###############################################################################
## This script updates AGOL feature service data. It pulls data from the     ##
## oracle database and creates a pandas dataframe. It then deletes old data  ##
## from the feature service and loads the new data using the append method.  ##
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
import warnings

# AUTHENTICATE ARCGIS CREDENTIALS
# Using ArcGIS Pro to authenticate, change authentication scheme if necessary
gis = GIS("PRO")

# CONNECT TO ORACLE
# Enable thick mode, using oracle instant client and tnsnames.ora
oracledb.init_oracle_client()

# Access .env variables
load_dotenv(dotenv_path = os.path.expandvars(r"%USERPROFILE%\.config\secrets\.env"))
# Oracle credentials
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
# Ensure columns are uppercase for comparison consistency later
df_fields.columns = df_fields.columns.str.upper()

# Extract all spatial tables from oracle
# Create an empty dictionary to hold all dataframes
dataframes = {}

# Get the list of table names from df_fields
table_names = df_fields['TABLE_NAME'].unique()
print("Getting tables from the database...")

# Make a separate pandas dataframe for each spatial table in the database
# Ensure that geometry column is handled correctly (convert to wkt)
with engine.connect() as connection:
    for table_name in table_names:
        try:
            print(f"--- Processing table: '{table_name}' ---")

            columns = df_fields[df_fields['TABLE_NAME'] == table_name]['COL_NAME'].tolist()

            # Join the known column names into a single string
            columns_sql_str = ", ".join(columns)

            # Build the final SELECT statement
            # Manually add the SDO_GEOM conversion for the 'shape' column to every query
            final_columns_str = f"{columns_sql_str}, TBL.SHAPE.SDO_SRID as SHAPE_SRID, SDO_UTIL.TO_WKTGEOMETRY(SHAPE) AS SHAPE_WKT"

            # Construct the final SQL query
            query = text(f'SELECT {final_columns_str} FROM {schema}.{table_name} TBL')

            # Execute the query and store the resulting dataframe
            df = pd.read_sql_query(query, con = connection)
            if df.shape_srid.nunique() > 1:
                warnings.warn("SHAPE column in the DataFrame contains multiple SRID values.")
            dataframes[table_name] = df
            print(f"   Successfully loaded '{table_name}'")

        except Exception as e:
            print(f" FAILED to load table '{table_name}': {e}")

# Make all dataframes and columns in dataframes uppercase
# This is how everything is named in AGOL
upper_dataframes = {
    key.upper(): df.rename(columns = str.upper) 
    for key, df in dataframes.items()
}
print("Converted all data table names and columns to uppercase.")

# DATA TYPE MATCHING FUNCTION
# Maps pandas data types to AGOL field types 
def map_pandas_to_agol_type(pd_dtype) -> str:
    """
    Maps Pandas dtypes to ArcGIS field types.
    """
    dtype_name = pd_dtype.name.lower()
    
    if 'int' in dtype_name:
        # Pandas integer to esri type interger
        return "esriFieldTypeInteger"
    elif 'float' in dtype_name or 'double' in dtype_name:
        # Pandas floating-point number to esri type double
        return "esriFieldTypeDouble"
    elif 'datetime' in dtype_name:
        # Pandas datetime converted to esri type date
        return "esriFieldTypeDate"
    elif 'bool' in dtype_name:
        # Booleans stored as intergers in AGOL
        return "esriFieldTypeInteger"
    else: # Any other column type will be converted to esri type string
        return "esriFieldTypeString"

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

        # SCHEMA COMPARISON AND UPDATE LOGIC 
        
        # Get the list of fields from the source dataframe
        # Exclude temporary and internal columns used for Oracle geometry handling
        SOURCE_EXCLUSIONS = {'SHAPE_SRID', 'SHAPE_WKT'}
        source_fields = set(source_df.columns.str.upper().tolist()) - SOURCE_EXCLUSIONS

        # Get the list of fields from the target AGOL Layer
        # Exclude AGOL internal/system fields that cannot be managed
        AGOL_EXCLUSIONS = {'OBJECTID', 'SHAPE', 'GLOBALID', 'SHAPE__AREA', 'SHAPE__LENGTH'}
        target_fields = set(
            f['name'].upper() for f in target_layer.properties.fields
        ) - AGOL_EXCLUSIONS

        # Identify fields to add and/or fields to delete
        fields_to_add = source_fields - target_fields
        fields_to_delete = target_fields - source_fields
        
        print(f" - Source Columns: {source_fields}")
        print(f" - Target Columns: {target_fields}")
        
        # Deleting Fields 
        if fields_to_delete:
            print(f" - Deleting fields: {fields_to_delete}")

            # Construct the working payload: {"fields": [{"name": "FIELD1"}, {"name": "FIELD2"}]}
            fields_to_delete_list = []
            for field_name in fields_to_delete:
                fields_to_delete_list.append({"name": field_name})

            delete_field_payload = {"fields": fields_to_delete_list}
            try:
                delete_result = target_layer.manager.delete_from_definition(delete_field_payload)
                if delete_result.get('success'):
                    print(f" Successfully deleted fields: {fields_to_delete}")
                else:
                    print(f" Failed to delete fields: {fields_to_delete}. Result: {delete_result}")
            except Exception as e:
                 print(f" Error deleting fields: {e}")
        else:
            print("   - No fields to delete from AGOL feature service.")

        # Adding Fields (using data type matching function)
        if fields_to_add:
            print(f" - Adding fields: {fields_to_add}")
            
            new_field_definitions = []
            
            for field_name in fields_to_add:
                # Inspect the Pandas dtype of the column
                pd_dtype = source_df[field_name].dtype
                
                # Map the Pandas dtype to the AGOL type using the map_pandas_to_agol_type function
                agol_type = map_pandas_to_agol_type(pd_dtype)
                
                field_def = {
                    "name": field_name,
                    "type": agol_type,
                    "alias": field_name.title()
                }
                
                # Add 'length' only for string fields
                if agol_type == "esriFieldTypeString":
                    field_def["length"] = 255 # Safe default string field length
                    
                new_field_definitions.append(field_def)
                print(f" - Preparing to add '{field_name}' (Pandas dtype: {pd_dtype}) as {agol_type}")
                
            add_field_payload = {"fields": new_field_definitions}
            
            try:
                add_result = target_layer.manager.add_to_definition(add_field_payload)
                if add_result.get('success'):
                    print(f" Successfully added fields: {fields_to_add}")
                else:
                    print(f" Failed to add fields: {fields_to_add}. Result: {add_result}")
            except Exception as e:
                print(f" Error adding fields: {e}")
        else:
            print("   - No fields to add to AGOL feature service.")

        print("  - Finished field/schema comparison and update logic.")


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
        sedf.drop(['SHAPE_WKT','SHAPE_SRID'], axis = 1, inplace = True)
        
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