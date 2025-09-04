#This script updates ArcGIS Online feature service and layer metadata
#It pulls info from the oracle database and uses it to fill an XML metadata template
#The XML file is passed to the AGOL feature service
#Layer level metadata (layers within the feature servcice) is also updated

#IMPORT LIBRARIES
import json, os, sys, base64, tempfile
import xml.etree.ElementTree as ET
import sqlalchemy
import oracledb
from sqlalchemy import create_engine, select, MetaData, Table, text
from sqlalchemy.engine import create_engine
from datetime import datetime
import arcgis
from arcgis import gis
from arcgis.gis import GIS
from arcgis.features import FeatureLayerCollection, FeatureLayer

#AUTHENTICATE ARCGIS CREDENTIALS
#using ArcGIS Pro to authenticate, change authentication scheme if necessary
gis = GIS("PRO")

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

#UPDATE FEATURE LEVEL METADATA
#make a temporary xml file from template (ARCGIS_METADATA_TEMPLATE.xml)by pulling data from oracle metadata table
#for each survey, then push to arcgis online to update survey metadata
#names of surveys, from oracle table
survey_names=["ECOMON","SCALLOP","HL","BTS","CSBLL","MMST","NARW","GOMBLL","SEAL","TURTLE","EDNA", "SHRIMP", "COASTSPAN","OQ","SC"]

with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".xml") as temp_file:
  
  for survey_short in survey_names:
  
    #use metadata template (already has correct parent and child elements to fulfill metadata requirements)
    metadata_xml = "python/ARCGIS_METADATA_TEMPLATE.xml"
    #import xml and get xml roots
    tree = ET.parse(metadata_xml)
    root = tree.getroot()
  
    metadata_table = 'smit_meta_features' #metdata table name in oracle
    metadata = MetaData()
    table = Table(metadata_table, metadata, autoload_with=engine)
    #query the table for metadata based on the short survey names (strata_short)
    
    with engine.connect() as connection:
      query = select(table).where(table.c.strata_short==survey_short)
      result = connection.execute(query).fetchone() #fetch a row from metadata table for survey
  
    #extract metadata values
    if result:
      title = result.survey_name
      abstract = result.abstract
      purpose = result.purpose
      tags = result.tags.split(', ')
      credits = result.useterms
      pub_date = result.publish_date
      meta_contact = result.meta_contact_name
      meta_title = result.meta_contact_title
      meta_email = result.meta_contact_email
      source = result.source
      useterms = result.useterms
      link= result.link
      extent_n = result.geoextent_n
      extent_s = result.geoextent_s
      extent_e = result.geoextent_e
      extent_w = result.geoextent_w
      rest_url = result.rest_url
      file_ID = result.file_id
      thumbnail = result.thumbnail
      #convert thumbnail to base 64 encoded
      encoded_thumbnail = base64.b64encode(thumbnail).decode("utf-8")
    else:
      raise ValueError("No metadata found in SQL Table")
    
    print(f"Finished extracting metadata for {survey_short} from oracle db.") 
  
    #edit xml template file using metadata from oracle
    #update thumbnail
    thumbnail_element = root.find(".//Binary/Thumbnail/Data")
    thumbnail_element.text = encoded_thumbnail
    #update abstract
    abs_element = root.find(".//dataIdInfo/idAbs")
    abs_element.text = f'<p>{link if link else ""}<br>{abstract}</p>'
    #update title
    title_element = root.find(".//dataIdInfo/idCitation/resTitle")
    title_element.text = title
    #update publish date
    date_element = root.find(".//dataIdInfo/idCitation/date/pubDate")
    #change timetime to string
    datetime_string = pub_date.strftime('%Y-%m-%d %H:%M:%S')
    date_element.text = datetime_string
    #update geographic extent
    geowest_element = root.find(".//dataIdInfo/dataExt/geoEle/GeoBndBox/westBL")
    geowest_element.text = str(extent_w)
    geoeast_element = root.find(".//dataIdInfo/dataExt/geoEle/GeoBndBox/eastBL")
    geoeast_element.text = str(extent_e)
    geonorth_element = root.find(".//dataIdInfo/dataExt/geoEle/GeoBndBox/northBL")
    geonorth_element.text = str(extent_n)
    geosouth_element = root.find(".//dataIdInfo/dataExt/geoEle/GeoBndBox/southBL")
    geosouth_element.text = str(extent_s)
    #update tags by itearting through list of tags
    tags_element = root.find(".//dataIdInfo/searchKeys")
    #delete old tags
    for tag in list(tags_element):
      tags_element.remove(tag)
    #iterate through tags list
    for tag in tags:
      tag_element = ET.SubElement(tags_element, "keyword")
      tag_element.text = tag 
    #update purpose statement
    purp_element = root.find(".//dataIdInfo/idPurp")
    purp_element.text = purpose
    #update credits
    credit_element = root.find(".//dataIdInfo/idCredit")
    credit_element.text = source
    #update use terms
    constraint_element = root.find(".//dataIdInfo/resConst/Consts/useLimit")
    constraint_element.text = useterms
    #update metadata contact info
    email_element = root.find(".//mdContact/rpCntInfo/cntAddress/eMailAdd")
    email_element.text = meta_email
    contact_element = root.find(".//mdContact/rpIndName")
    contact_element.text = meta_contact
    meta_title_element = root.find(".//mdContact/rpPosName")
    meta_title_element.text = meta_title 
  
    #write xml to temp file
    ET.ElementTree(root).write(temp_file.name)
    print('Metadata converted to temp XML file.')
    #get name of temp file
    xml_metadata = temp_file.name
    
    #get arcgis online item using file id
    item = gis.content.get(file_ID)
    #update metadata for feature service item 
    item.update(metadata = xml_metadata)
    #create a feature layer collection item (to update metadata on REST Service page)
    item = gis.content.get(file_ID)
    flc = FeatureLayerCollection.fromitem(item)
    
    #create json dictionary to update feature layer collection (metadata on the REST Service page)
    item_properties = {
    "title" : item.title,
    "tags" : item.tags,
    "snippet" : item.snippet,
    "description" : item.description,
    "serviceDescription":item.description,
    "licenseInfo" : item.licenseInfo,
    "accessInformation" : item.accessInformation,
    "copyrightText": item.licenseInfo
    }
    flc.manager.update_definition(item_properties)

    #update the thumbnail on the feature service landing page
    #for some reason the landing page thumbnail doesn't update when the metadata thumbnail is updated
    with tempfile.NamedTemporaryFile(delete=False, suffix = ".jpg") as tmp_file:
      tmp_file.write(thumbnail)
      tmp_file_path = tmp_file.name
    
    item.update(thumbnail= tmp_file_path) #calling the thumbnail item specifically updates the thumbnail
    print(f"Thumbnail on landing page updated for {item.title}.")
    
    print(f"Metadata for {item.title} updated successfully.")

print("All feature service metadata updated!")    

#UPDATE LAYER LEVEL METADATA 
#layer level metadata cannot be updated with XML, need to use a json dictionary
#create json dictionary using item properties from hosted feature service
for survey_short in survey_names:
  
  #extract the layer ID value from oracle metadata table using survey name
  metadata_table = 'smit_meta_features' #metdata table name in oracle
  metadata = MetaData()
  table = Table(metadata_table, metadata, autoload_with=engine)
  with engine.connect() as connection:
    query = select(table).where(table.c.strata_short==survey_short)
    result = connection.execute(query).fetchone()
  layerID = result.file_id
  
  item = gis.content.get(layerID)
    
  with engine.connect() as connection:
    query = select(table).where(table.c.strata_short==survey_short)
    result = connection.execute(query).fetchone()
  rest_url = result.rest_url    

  layer_nums = ['0', '1']
  #update script if there are more than 2 layers, add numbers to layer_nums 
  for layer_num in layer_nums: 

    layer_url = f"{rest_url}/{layer_num}"

    try: 
      #pull out abstract from oracle metadata table to fill in the layer level description
      table_name = "smit_meta_layers"
      column_name = "abstract"
      with engine.connect() as connection:
        metadata= MetaData()
        table = Table(table_name, metadata, autoload_with=engine)
        query = select(table.c[column_name]).where(table.c.rest_url == f'{layer_url}')
        
        result = connection.execute(query).fetchone()
      description = result[0] if result and result[0] is not None else ''
      
      layer_properties = {
        "description" : description,
        "licenseInfo" : item.licenseInfo,
        "copyrightText": item.licenseInfo
        }
      
      layer = FeatureLayer(layer_url)
      print(f"{survey_short} layer {layer_num} exists, proceeding with update...")
      layer.manager.update_definition(layer_properties)
      print(f"{survey_short} layer {layer_num} updated successfully!")
    except Exception as e:
      print(f"layer {layer_num} does not exist or could not be retrieved.") 
      
print("All layer level metadata updated!")