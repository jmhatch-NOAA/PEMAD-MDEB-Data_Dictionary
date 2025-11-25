
###############################################################################
## This script updates AGOL feature service pop-ups (what you see when you   ##
## click on a data attribute in a webmap). It hides the OBJECTID column and  ##
## creates default popup settings for any newly added columns to the dataset.## 
###############################################################################

# IMPORT LIBRARIES
from dotenv import load_dotenv
import os
import pandas as pd
import oracledb
from sqlalchemy import create_engine
from arcgis.gis import GIS

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

# CONFIGURE FIELDS FOR POPUPS 
# Popup configuration for OBJECTID (to make OBJECTID hidden in popups)
objectid_config = {
            "fieldName": "OBJECTID",
            "format": {
                "digitSeparator": False,
                "places": 0
            },
            "isEditable": False,
            "label": "OBJECTID",
            "visible": False  # This ensures the OBJECTID col is hidden in popups
        }

# Default configuration for any NEW field that needs to be added to the popup.
default_new_field_config = {
    "isEditable": True, 
    "visible": True,    
    "format": None      # Use default formatting for simplicity
}

# HELPER FUNCTION to add missing fields to popup
def create_field_info(field_name, field_alias, config):
    """
    Creates a standard fieldInfo dictionary for the popup.
    """
    info = {
        "fieldName": field_name,
        "isEditable": config.get("isEditable", True),
        "visible": config.get("visible", True),
        "label": field_alias,
    }
    # Add format if it exists in the configuration
    if config and config.get("format") is not None:
        info["format"] = config["format"]
    
    return info

# FUNCTION TO ADD MISSING FIELDS TO POPUP 
def add_missing_fields_to_popup(layer_object, popupInfo):
    """
    Compares the actual layer schema (via layer_object) with fields in popupInfo 
    and adds missing ones back into popupInfo.
    """
    # Use .properties.fields to access the schema
    layer_fields_schema = layer_object.properties.fields 
    
    # Get the list of fields from the layer object 
    layer_field_names = {f['name'].lower() for f in layer_fields_schema} 
    
    # Get the list of fields currently defined in the main fieldInfos part of the popup
    existing_popup_field_names = {f['fieldName'].lower() for f in popupInfo.get('fieldInfos', [])}

    # Identify missing fields
    missing_field_names = layer_field_names - existing_popup_field_names
    
    if not missing_field_names:
        return 0 # No changes needed

    added_count = 0
    
    # Iterate through the schema to get the full name and alias for missing fields
    for field_schema in layer_fields_schema:
        field_name = field_schema['name']
        
        if field_name.lower() in missing_field_names:
            field_alias = field_schema.get('alias', field_name)
            
            # Create the default fieldInfo structure for the missing field (using the create_field_info function)
            new_field_info = create_field_info(
                field_name, 
                field_alias, 
                config=default_new_field_config
            )
            
            # --- Insert the new field definition ---
            
            # Add to the main fieldInfos list
            if 'fieldInfos' not in popupInfo:
                 popupInfo['fieldInfos'] = []
            popupInfo['fieldInfos'].append(new_field_info)

            # Add to the 'fields' popupElements list (if it exists)
            for element in popupInfo.get('popupElements', []):
                if element.get('type') == 'fields':
                    if 'fieldInfos' not in element:
                        element['fieldInfos'] = []
                    element['fieldInfos'].append(new_field_info)
            
            added_count += 1
            
    return added_count

# FUNCTION TO UPDATE POPUPS (add fields and hide OBJECTID field)
def update_popup_info(fs_item_id):
    """
    Updates popupInfo for all layers in a Feature Service, including 
    adding missing fields and setting standard configs for specific fields.
    """
    try:
        fs_item = gis.content.get(fs_item_id)
        # Check if the item is a Feature Service (or Feature Layer Collection)
        if fs_item.type not in ['Feature Service', 'Feature Layer Collection']:
             print(f" Item {fs_item_id} is not a Feature Service/Collection. Skipping.")
             return
             
        print(f"\nProcessing Item: {fs_item.title} ({fs_item_id})")

        # Get the editable definition
        fs_def = fs_item.get_data()

        if 'layers' not in fs_def or not fs_def['layers']:
            print("  No layers found in the service definition. Skipping.")
            return

        service_updated = False
        
        # Iterate over the layer definitions for the update
        for lyr_index, layer_def in enumerate(fs_def['layers']):
            layer_name = layer_def.get('name', f"Layer {lyr_index}")
            print(f"   -- Inspecting Layer {lyr_index}: '{layer_name}' --")
            
            # Get the layer object for schema access
            try:
                layer_object = fs_item.layers[lyr_index]
            except IndexError:
                print(f"  Cannot access layer object for index {lyr_index}. Skipping layer.")
                continue

            popupInfo = layer_def.get('popupInfo')
            
            # Create a default popupInfo structure if missing
            if not popupInfo:
                print(f" Layer {lyr_index} missing 'popupInfo'. Creating a default structure.")
                popupInfo = {"title": layer_name, "fieldInfos": [], "popupElements": [{"type": "fields", "fieldInfos": []}]}
                layer_def['popupInfo'] = popupInfo
            
            # --- Add Missing Fields ---
            added_count = add_missing_fields_to_popup(layer_object, popupInfo)
            if added_count > 0:
                print(f" Added {added_count} missing field(s) to the popupInfo.")
                service_updated = True

            # --- Update Standard Fields (OBJECTID) ---
            updated_count = 0
            
            popup_parts = []
            if 'fieldInfos' in popupInfo:
                popup_parts.append(popupInfo['fieldInfos'])
            
            for element in popupInfo.get('popupElements', []):
                if element.get('type') == 'fields' and 'fieldInfos' in element:
                    popup_parts.append(element['fieldInfos'])

            for field_infos in popup_parts:
                for field_config in field_infos:
                    field_name = field_config.get('fieldName')
                    
                    if field_name == 'OBJECTID':
                        field_config.update(objectid_config)
                        updated_count += 1

            if updated_count > 0:
                print(f" Updated {updated_count} specific field configurations.")
                service_updated = True
            
            if added_count == 0 and updated_count == 0:
                 print(" No changes needed for this layer.")

        # --- Update the Item definition only if changes were made to any layer ---
        if service_updated:
            fs_item.update({"text" : fs_def}) 
            print(f"Successfully pushed the updated definition for {fs_item.title} to AGOL.")
        else:
            print(f" No updates were applied to {fs_item.title}.")

    except Exception as e:
        print(f" An error occurred while processing {fs_item_id}: {e}")

# Make a list of item ids from the df_layers dataframe
fs_item_ids = df_layers['file_id'].tolist()

# RUN THE FUNCTION
print("--- Starting Popup Batch Update ---")
for item_id in fs_item_ids:
    update_popup_info(item_id)

print("Batch Update Complete")