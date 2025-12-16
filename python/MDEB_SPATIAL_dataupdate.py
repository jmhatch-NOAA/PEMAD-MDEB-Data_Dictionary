###############################################################################
## This script updates AGOL feature service data. It pulls data from the     ##
## oracle database and creates file geodatabases. It then updates the        ##
## feature services using the zipped file geodatabases.                      ##
###############################################################################

# IMPORT LIBRARIES
from dotenv import load_dotenv
import os
import pandas as pd
import geopandas as gpd
import oracledb
import zipfile
import shutil
from sqlalchemy import create_engine, text
from arcgis.gis import GIS
from arcgis.geometry import Geometry
from shapely.wkt import loads as wkt_loads
from arcgis.features import FeatureLayerCollection

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

# Add a column to df_layers to capture the hosted feature service name
# Extract from the url
regex_pattern = r'.*\/services\/([^/]+)'
# Use the .str.extract() method
df_layers['service_name'] = df_layers['rest_url'].str.extract(regex_pattern)

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

            # Order and organize columns consistenly
            # Convert columns to uppercase immediately for consistent processing
            df.columns = [col.upper() for col in df.columns]

            # Define the columns to be placed first
            first_columns = ['OID', 'SURVEY_NAME']

            # Get the remaining columns, excluding the first two
            all_columns = df.columns.tolist()
            remaining_columns = [col for col in all_columns if col not in first_columns]

            # Sort the remaining columns alphabetically
            remaining_columns.sort()

            # Create the final desired column order
            final_column_order = first_columns + remaining_columns

            # Reindex the DataFrame to apply the new column order
            df = df.reindex(columns=final_column_order)
            dataframes[table_name] = df
            print(f"  Successfully loaded '{table_name}'")

        except Exception as e:
            print(f" FAILED to load table '{table_name}': {e}")

 # Make all dataframes uppercase
 # This is how everything is named in AGOL
upper_dataframes = {
    key.upper(): df 
    for key, df in dataframes.items()
}
print("Converted all data table names and columns to uppercase.")

# CREATION OF FILE GEODATABASES
# Loop through each row in df_layers to create a layer within a file geodatabase
# The first layer will create the file geodatabase and any subsequent layers will be added to the 
# file geodatabase based on matching service names
# Make sure to correctly handle geometry (use shapely and create spatially enabled dataframe)

# Create folder to hold all file geodatabases
fgdb_folder = "gdb"
os.mkdir(fgdb_folder)

for index, layer_row in df_layers.iterrows():
    try:
        item_id = layer_row['file_id']
        rest_url = layer_row['rest_url']
        table_name = layer_row['table_name'] # The key to retrieve the data frame from the dictionary
        service_name = layer_row['service_name'] # Used to name the FGDB (zipped FGDB must match the rest service name exactly)
        
        print(f"--- Processing Layer: '{table_name}' ---")

        # Get DataFrame for this layer
        source_df = upper_dataframes.get(table_name)
        if source_df is None or source_df.empty:
            print(f"  - No data found for table '{table_name}'. Skipping.")
            continue

        # Create spatially enabled dataframe
        print("  - Converting WKT to geometry using Shapely...")
        sedf = source_df.copy()

        # Get SRID from Oracle data
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

        # Convert sedf to a geopandas dataframe 
        gdf = gpd.GeoDataFrame(sedf, geometry='SHAPE', crs=f'EPSG:{oracle_srid}')

        # Remove the shape_srid column that is automatically created by geopandas
        if 'SHAPE_SRID' in gdf.columns:
            gdf = gdf.drop(columns=['SHAPE_SRID'])

        # Create a file geodatabase from geopandas dataframe
        # Create within the gdb folder
        gdf.to_file(
            filename= f"{fgdb_folder}/{service_name}.gdb",
            layer = table_name,
            driver = "OpenFileGDB"
        )

    except Exception as e:
        print(f"An unhandled error occurred for layer '{layer_row.get('layer_name', 'N/A')}': {e}\n")

# ZIP COMPLETED FILE GEODATABASES AND OVERWRITE AGOL HOSTED FEATURE SERVICES

if not os.path.exists(fgdb_folder):
    print(f"Error: The directory '{fgdb_folder}' was not found. Cannot proceed with update.")
else:
    # Iterate through all items in the 'gdb' directory
    for item_name in os.listdir(fgdb_folder):
        if item_name.endswith(".gdb") and os.path.isdir(os.path.join(fgdb_folder, item_name)):
            fgdb_name = item_name                      # ex.'ServiceA.gdb'
            service_name_base = fgdb_name.split('.')[0] # ex. 'ServiceA'
            fgdb_path = os.path.join(fgdb_folder, fgdb_name)
            
            try:
                print(f"\nProcessing File Geodatabase: {fgdb_name}")

                # Get the row in df_layers that corresponds to the feature service
                service_row = df_layers[df_layers['service_name'] == service_name_base].iloc[0]
                # Retrieve feature service file id
                service_item_id = service_row['file_id'] 
                
                # Zip the FGDB
                zip_filename = service_name_base + '.zip'
                zip_filepath = os.path.join(fgdb_folder, zip_filename)
                base_dir = fgdb_folder # 'gdf'
                
                print(f" - Starting compression for: {fgdb_name}")
                with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
                    # Walk the FGDB folder to add contents recursively
                    for root, dirs, files in os.walk(fgdb_path):
                        # Determine the relative path inside the zip file
                        archive_root = os.path.relpath(root, base_dir)
                        for file in files:
                            full_path = os.path.join(root, file)
                            archive_path = os.path.join(archive_root, file)
                            zf.write(full_path, archive_path)
                
                print(f" - Successfully created zip file: {zip_filepath}")

                # Update the AGOL hosted feature service 
                # Get the Item object for the service
                service_item = gis.content.get(service_item_id)

                # Get the feature layer collection from the service item
                flc = FeatureLayerCollection.fromitem(service_item)
                
                # Use the overwrite method to update the data
                print(f" - Uploading zip and overwriting data for Item ID: {service_item_id}")
                update_result = flc.manager.overwrite(zip_filepath)
                
                # Print success or failure message
                if update_result.get('success'):
                    print(" Success: Hosted Feature Service updated successfully.")
                else:
                    print(f" Failed: Update failed. Messages: {update_result.get('messages')}")

                # Clean up temporary files
                print("- Cleaning up temporary FGDB and zip file.")
                if os.path.exists(fgdb_path):
                    shutil.rmtree(fgdb_path) # Remove the .gdb directory
                if os.path.exists(zip_filepath):
                    os.remove(zip_filepath)  # Remove the .zip file

            except IndexError:
                print(f" - WARNING: Could not find matching AGOL service ID for service name '{service_name_base}'. Skipping update.")
            except Exception as e:
                print(f" - An unhandled error occurred for FGDB '{fgdb_name}': {e}")

# Final cleanup of the parent directory if empty
if os.path.exists(fgdb_folder) and not os.listdir(fgdb_folder):
    os.rmdir(fgdb_folder)

print("\nScript finished. All AGOL feature service data was updated.")