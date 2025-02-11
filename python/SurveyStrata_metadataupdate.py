#set python environment in r console
#library(reticulate)
#use_condaenv("path/to/conda/environ")

#edit metadata xml file from arcgis online and update using metadata stored in oracle database
#import libraries
import tempfile
import json
import os, sys
import arcpy
import xml.etree.ElementTree as ET
import sqlalchemy
from sqlalchemy import create_engine, select, MetaData, Table
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import create_engine
from datetime import datetime
from arcgis.gis import GIS
from arcgis import gis
from arcgis.features import FeatureLayerCollection, FeatureLayer

#authenticate arcgis credentials
gis = GIS("PRO")

#CONNECT TO ORACLE
#Connect to oracle database using SQL alchemy engine
DIALECT = 'oracle'
SQL_DRIVER = 'cx_oracle'
USERNAME = '' #enter your username
PASSWORD = '' #enter your password
HOST = '' #enter the oracle db host url
PORT =   # enter the oracle port number
SERVICE = '' # enter the oracle db service name
ENGINE_PATH_WIN_AUTH = DIALECT + '+' + SQL_DRIVER + '://' + USERNAME + ':' + PASSWORD +'@' + HOST + ':' + str(PORT) + '/?service_name=' + SERVICE
engine = create_engine(ENGINE_PATH_WIN_AUTH)
connection= engine.connect()
Session = sessionmaker(bind=engine)
session= Session()

#names of surveys, from oracle table

survey_names = ["SCALLOP","HL","BTS","CSBLL","MMST","NARW","GOMBLL","SEAL","TURTLE","EDNA","ECOMON","OQ","SC", "SHRIMP"]

#first pull item ID from oracle
#download an xml file from arcgis to edit using the item id

with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".xml") as temp_file:


  for survey_short in survey_names:
  
    #extract the layer ID value from oracle metadata table using survey name
    layer_sql_query = f"SELECT FILE_ID from SMIT_{survey_short}_META"
    layerID = session.execute(layer_sql_query).fetchone()
    layerID = str(layerID[0])
    
    item = gis.content.get(layerID)
    #get metadata 
    metadata_xml = item.metadata
    #import xml and get xml roots
    tree = ET.parse(metadata_xml)
    root = tree.getroot()
  
    metadata_table = f'SMIT_{survey_short}_META' #metdata table name in oracle
    column_name = 'table_name'
    metadata = MetaData(bind=engine)
    table = Table(metadata_table, metadata, autoload_with=engine)
    #query the table for metadata based on the name of the metadata table
    
    with engine.connect() as connection:
        query = select([table]).where(table.c[column_name].is_(None))
        result = connection.execute(query).fetchone() #fetch first row from metadata table
        
    if result:
      print(result.keys())
     
    print('Done')  

    #extract metadata values
    if result:
      title = result.title
      abstract = result.abstract
      purpose = result.purpose
      tags = result.tags.split(', ')
      credits = result.useterms
      pub_date = result.publish_date
      topic_cats = result.topic_cats.split(', ')
      meta_contact = result.meta_contact_name
      meta_title = result.meta_contact_title
      meta_role = result.meta_contact_role
      meta_email = result.meta_contact_email
      source = result.source
      useterms = result.useterms
      link= result.link
      lang = result.meta_language
      extent_n = result.geoextent_n
      extent_s = result.geoextent_s
      extent_e = result.geoextent_e
      extent_w = result.geoextent_w
      rest_url = result.rest_url
      file_ID = result.file_id
    else:
      raise ValueError("No metadata found in SQL Table")
    
    print('Done') 
  
    #edit xml file using metadata from oracle
    #first remove the thumbnail element, this cannot be updated using xml
    to_remove = root.find(".//Binary")
    if to_remove is not None:
      root.remove(to_remove)
    #update abstract
    abs_element = root.find(".//dataIdInfo/idAbs")
    abs_element.text = f'<p>{link if link else ""}<br><br>{abstract}</p>'
    #update title
    title_element = root.find(".//dataIdInfo/idCitation/resTitle")
    title_element.text = title
    #update publish date
    date_element = root.find(".//dataIdInfo/idCitation/date/pubDate")
    #change timetime to string
    datetime_string = pub_date.strftime('%Y-%m-%d')
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
    # #update tags by itearting through list of tags
    tags_element = root.find(".//dataIdInfo/searchKeys")
    #delete old tags
    for tag in list(tags_element):
      tags_element.remove(tag)
    #iterate through tags list
    for tag in tags:
      tag_element = ET.SubElement(tags_element, "keyword")
      tag_element.text = tag 
    #updatepurpose statement
    purp_element = root.find(".//dataIdInfo/idPurp")
    purp_element.text = purpose
    #update credits
    credit_element = root.find(".//dataIdInfo/idCredit")
    credit_element.text = source
    #update use terms
    constraint_element = root.find(".//dataIdInfo/resConst/Consts/useLimit")
    constraint_element.text = useterms
    #update File ID
    fileid_element = root.find(".//mdFileID")
    fileid_element.text = file_ID
    #update metadata language
    lang_element = root.find(".//mdLang/languageCode")
    lang_element.text = lang
    #update metadata contact info
    email_element = root.find(".//mdContact/rpCntInfo/cntAddress/eMailAdd")
    email_element.text = meta_email
    contact_element = root.find(".//mdContact/rpIndName")
    contact_element.text = meta_contact
    meta_title_element = root.find(".//mdContact/rpPosName")
    meta_title_element.text = meta_title 
    
    #update REST URL
    url_element = root.find(".//distInfo/distTranOps/onLineSrc/linkage")
    url_element.text = rest_url
    #update topic categories by iterating through topic cat list
    topiccats_element = root.find(".//dataIdInfo/tpCat")
    
    #delete old topic cats
    for topic_cat in list(topiccats_element):
      topiccats_element.remove(topic_cat)
    
    #add new cats
    for topic_cat in topic_cats:
      topiccat_element = ET.SubElement(topiccats_element, "TopicCatCd")
      topiccat_element.text = topic_cat
    
    
    
    # #write xml to temp file
    ET.ElementTree(root).write(temp_file.name)
    # #get name of temp file
    temp_file_name = temp_file.name
    # 
    # #update metadata for feature service
    item.update(metadata = temp_file_name)
    
    print(f"Metadata for {item.title} updated successfully")

print("All feature service metadata updated!")    
    
# #update metadata for individual layers within feature services
# #create json dictionary using item properties from feature service 
survey_names = ["SCALLOP","HL","BTS","CSBLL","MMST","NARW","GOMBLL","SEAL","TURTLE","EDNA","ECOMON","OQ","SC", "SHRIMP"]
for survey_short in survey_names:
  
  #extract the layer ID value from oracle metadata table using survey name
  layer_sql_query = f"SELECT FILE_ID from SMIT_{survey_short}_META"
  layerID = session.execute(layer_sql_query).fetchone()
  layerID = str(layerID[0])
  
  item = gis.content.get(layerID)
  #extract REST url from metadata table
  metadata_table = f'SMIT_{survey_short}_META' #metdata table name in oracle
  column_name = 'table_name'
  metadata = MetaData(bind=engine)
  table = Table(metadata_table, metadata, autoload_with=engine)
  #query the table for metadata based on the name of the metadata table
    
  with engine.connect() as connection:
      query = select([table]).where(table.c[column_name].is_(None))
      result = connection.execute(query).fetchone() #fetch first row from metadata table
  rest_url = result.rest_url     

  item_properties = {
  "title" : item.title,
  "tags" : item.tags,
  "snippet" : item.snippet,
  "summary" : item.snippet,
  "description" : item.description,
  "serviceDescription":item.description,
  "licenseInfo" : item.licenseInfo,
  "accessInformation" : item.accessInformation,
  "copyrightText": item.licenseInfo
  }
  # 
  feature_service = FeatureLayer(rest_url)
  feature_service.manager.update_definition(item_properties)
  layer_id = '0'
  layer_url = f"{rest_url}/{layer_id}"
  layer = FeatureLayer(layer_url)
  print(f"{survey_short} layer {layer_id} exists, proceeding with update...")
  layer.manager.update_definition(item_properties)
  print(f"{survey_short} layer {layer_id} updated successfully!")
    
  layer_id = '1'
  layer_url = f"{rest_url}/{layer_id}"
  try:
    layer = FeatureLayer(layer_url)
    print(f"{survey_short} layer {layer_id} exists, proceeding with update...")
    layer.manager.update_definition(item_properties)
    print(f"{survey_short} layer {layer_id} updated successfully!")
  except Exception as e:
    print(f"layer {layer_id} does not exist or could not be retrieved.")

print("All layer level metadata updated!")    
