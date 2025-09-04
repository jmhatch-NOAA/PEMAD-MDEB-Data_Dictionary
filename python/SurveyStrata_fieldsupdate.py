#This script updates field names, aliases, and descriptions for AGOL hosted feature service layers
#It pulls info from oracle database and updates an excel spreadsheet
#The excel spreadsheet is then passed to the hosted feature service layers to update field info in:
#1. the REST endpoint and
#2. the layer's pop-up JSON in the fieldsInfo section

#Original script from GitHub repo: https://github.com/lisaberrygis/AliasUpdater
#see original GitHub repo for more info

#IMPORT LIBRARIES
import tempfile
import os
import openpyxl
import pandas as pd
from io import BytesIO
import oracledb
from sqlalchemy import select, MetaData, Table, text
from sqlalchemy.engine import create_engine  
from arcgis.gis import GIS
from arcgis.features import FeatureLayer
from copy import deepcopy

#CONNECT TO ORACLE
#enable thick mode, using oracle instant client and tnsnames.ora
oracledb.init_oracle_client()
#Connect to oracle database using SQL alchemy engine and TNS names alias
tns_name = "" #TNS name
username = "" #oracle username
password = "" #oracle password
connection_string = f"oracle+oracledb://{username}:{password}@{tns_name}"
engine = create_engine(connection_string)
connection= engine.connect()

#AUTHENTICATE ARCGIS CREDENTIALS
#using ArcGIS Pro to authenticate, change authentication scheme if necessary
gis = GIS("PRO")  
#names of oracle spatial tables
survey_names=["ECOMON","SCALLOP","HL","BTS","CSBLL","MMST","NARW","GOMBLL","SEAL","TURTLE","EDNA", "SHRIMP", "COASTSPAN","OQ","SC"]

for tab in survey_names:
  
  #sql query to pull field names, aliases, and descriptions from oracle metadata fields tables
  sql_query = f"SELECT DISTINCT COL_NAME, COL_ALIAS, COL_DESCRIPTION from SMIT_META_FIELDS WHERE STRATA_SHORT = '{tab}'"
  with engine.connect() as connection:
    df = pd.read_sql(text(sql_query), connection)

  #add three columns to dataframe, keep them null- field type, number of decimals, and whether to have comma in number columns
  #the code doesn't work without having these columns, see description in original GitHub repo
  df['col_type'] = None
  df['col_dec'] = None 
  df['col_comma']= "no"
  #store the dataframe in memory as excel file
  excel_buffer = BytesIO()
  with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
    df.to_excel(writer, index=False, sheet_name='Sheet1')
    
  excel_buffer.seek(0)
  
  #save in memory file to temp file
  with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as temp_file:
    temp_file.write(excel_buffer.read())
    temp_file_path = temp_file.name
  
  #extract the layer ID value from oracle metadata table using survey layer name
  metadata_table = 'smit_meta_layers' #metdata table name in oracle
  metadata = MetaData()
  table = Table(metadata_table, metadata, autoload_with=engine)
  with engine.connect() as connection:
    query = select(table).where(table.c.strata_short==tab)
    result = connection.execute(query).fetchone()
  layerID = result.file_id

  # Get layer count from service
  updateItem = gis.content.get(layerID)
  restLayerCount = len(updateItem.layers)
  
  # format the path to the excel document so it is recognized as a path
  lookupTable = os.path.normpath(temp_file_path)
  
  # Read the lookup table and store the fields and alias names
  if lookupTable[-4:] != "xlsx":
      print("Please check your input. It needs to be a .xlsx excel file")
  else:
      print("Grabbing field and alias names from excel document...")
      # Open Master Metadata excel document
      workbook = openpyxl.load_workbook(lookupTable)
      sheet = workbook.active
      # Create an empty list to store all fields and alias names
      lookupList = []
  
      # Store values from master metadata excel doc and put into a list
      iter = sheet.iter_rows()
      iter.__next__()
      for row in iter:
          innerList = []
          for val in row:
              innerList.append(val.value)
          lookupList.append(innerList)

      looper = 0
      while restLayerCount > 0:
          # Access the feature layer intended for updating
          search = gis.content.search("id:" + layerID, item_type="Feature Layer")
          featureLayer = FeatureLayer.fromitem(search[0], layer_id=looper)
          layerName = search[0].name
          print("Updating layer " + str(looper) + " on " + str(layerName) + "...")
  
          print("\tGetting field definitions from service...")
          # Loop through fields in service and store JSON for any that are going to be updated
          layerFields = featureLayer.manager.properties.fields
  
          print("\tFinding fields to update...")
          # Loop through the fields in the service
          updateJSON = []
          for field in layerFields:
              fieldName = field['name']
              for lookupField in lookupList:
                  # As you loop through the service fields, see if they match a field in the excel document
                  if lookupField[0] == fieldName:
                      # store the field JSON from the online layer
                      fieldJSON = dict(deepcopy(field))
                      # assign the new alias name in JSON format
                      if lookupField[1]:
                          alias = lookupField[1]
                          fieldJSON['alias'] = alias
                      else:
                          alias = ""
                      # Assign field type, if specified
                      if lookupField[3]:
                          fldType = lookupField[3]
                      else:
                          fldType = ""
                      # assign the new field description in JSON format, if specified
                      if lookupField[2]:
                          longDesc = lookupField[2]
                          # Remove escape characters like double quotes, newlines, or encoding issues
                          longDesc = longDesc.replace('"', '\\\"').replace("\n", " ").replace("\t", " ").replace(u'\xa0', u' ').replace(">=", " greater than or equal to ").replace("<=", " less than or equal to ").replace(">", " greater than ").replace("<", " less than ")
                      else:
                          longDesc = ""
                      # Build the JSON structure with the proper backslashes and quotes
                      fieldJSON['description'] = "{\"value\":" + "\"" + longDesc + "\"" + ",\"fieldValueType\":\"" + fldType + "\"}"
                      fieldJSON.pop('sqlType')
                      if alias != "":
                          print("\t\tField '" + fieldName + "' will be updated to get the alias name '" + alias + "'")
                      if longDesc != "":
                          print("\t\t\t\tThe long description for this field was also updated")
                      if fldType != "":
                          print("\t\t\t\tThe field type for this field was also updated to: " + fldType)
                      # Create a python list containing any fields to update
                      updateJSON.append(fieldJSON)
  
          if updateJSON:
              print("\tUpdating alias names of the REST service...")
              UpdateDict = {'fields': updateJSON}
              # Use the update definition call to push the new alias names into the service
              featureLayer.manager.update_definition(UpdateDict)
          
              print("Field aliases, descriptions, and types updated on layer " + str(looper) + " of " + str(layerName)+ ".")

          looper += 1
          restLayerCount -= 1

print("Completed update of all fields!")