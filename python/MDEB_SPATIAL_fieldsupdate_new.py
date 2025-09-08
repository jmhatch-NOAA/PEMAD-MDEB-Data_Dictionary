###############################################################################
## This script updates field aliases and field descriptions for AGOL hosted  ##
## feature service layers. It pulls info from oracle database and creates    ##
## a JSON dictionary. It then updates the feature service at the REST        ##
## endpoint and in the fieldsInfo section.                                   ##
###############################################################################

#IMPORT LIBRARIES
from dotenv import load_dotenv
import os
import json
import pandas as pd
import oracledb
from sqlalchemy.engine import create_engine 
from arcgis.gis import GIS

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

#EXTRACT DATA
# query smit_meta_fields for field names, field aliases, and field descriptions
fields_sql_query = "SELECT * FROM mdeb_spatial.smit_meta_fields"
df_fields = pd.read_sql(fields_sql_query, con = connection)

# query smit_meta_layers to get layer info (layer name, url, and layer id)
layers_sql_query = "SELECT table_name, strata_short, rest_url, file_id FROM mdeb_spatial.smit_meta_layers"
df_layers = pd.read_sql(layers_sql_query, con = connection)

#UPDATE FIELDS
#loop through each layer in layers dataframe
for index, layer_row in df_layers.iterrows():
    try:
        #get layer information
        item_id = layer_row['file_id']
        layer_name = layer_row['table_name']
        rest_url = layer_row['rest_url']
        layer_index = int(rest_url.strip('/').split('/')[-1])

        print(f"Processing Layer: '{layer_name}' (Item ID: {item_id})")

        #Get the FeatureLayer object from its item ID and layer index
        feature_layer_item = gis.content.get(item_id)
        target_layer = feature_layer_item.layers[layer_index]

        #Get the layer's current definition (as JSON dictionary)
        current_definition = target_layer.properties

        #Filter the df_fields dataframe for the current layer, create df of field names, aliases, and descriptions
        relevant_fields_df = df_fields[df_fields['table_name'] == layer_name]

        # Build the JSON dictionary with the correctly formatted description string
        #description string needs to be formated a certain way to enable AGOL pop-ups are configured correctly
        field_updates = {}
        for _, row in relevant_fields_df.iterrows():
            simple_desc = row['col_description']

            # Handle potential null/empty descriptions
            if pd.isna(simple_desc):
                simple_desc = ""
            
            #create a dictionary with the required structure
            structured_desc_dict = {
                "value": simple_desc,
                "fieldValueType": ""
            }
            
            # Convert the dictionary to a JSON formatted string using json.dumps()
            # This automatically handles special characters and formatting.
            final_description_string = json.dumps(structured_desc_dict)

            # Add the complete field info to the JSON dictionary
            field_updates[row['col_name']] = {
                'alias': row['col_alias'],
                'description': final_description_string # Use the newly formatted string
            }
        #Loop through and update the field definitions (current_definition) using the field_updates dataframe
        for field in current_definition['fields']:
            if field['name'] in field_updates:
                field['alias'] = field_updates[field['name']]['alias']
                field['description'] = field_updates[field['name']]['description']

        #create the final updated JSON dictionary (only change the fields info)
        update_dictionary = {'fields':current_definition['fields']}

        #apply the update to the target AGOL layer
        result = target_layer.manager.update_definition(update_dictionary)

        #check results 
        if result.get('success', False):
            print(f"Successfully updated definition for '{layer_name}'.\n")
        else:
            print(f"Failed to update '{layer_name}': {result}\n")

    except Exception as e:
        print(f"An error occurred while processing '{layer_row.get('layer_name', 'N/A')}': {e}\n")

print("Script finished. Completed update of all fields.")