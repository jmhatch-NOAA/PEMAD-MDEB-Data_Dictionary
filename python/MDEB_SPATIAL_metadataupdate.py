###############################################################################
## This script is to edit metadata template xml file and fill using metadata ##
##   stored in oracle database to update ArcGIS Online feature service       ##
##   and layer metadata                                                      ##
###############################################################################

#IMPORT LIBRARIES
from dotenv import load_dotenv
import os
import base64
import tempfile
import pandas as pd
import xml.etree.ElementTree as ET
import oracledb
from sqlalchemy.engine import create_engine 
from arcgis.gis import GIS
from arcgis.features import FeatureLayerCollection, FeatureLayer

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

#UPDATE FEATURE LEVEL METADATA
#make a temporary xml file from template (ARCGIS_METADATA_TEMPLATE.xml) by pulling data from oracle metadata table
#for each survey, then push to arcgis online to update survey metadata

# query smit_meta_features
sql_query = "SELECT * FROM mdeb_spatial.smit_meta_features"
df_features = pd.read_sql(sql_query, con = connection)

#extract shortened survey names
survey_names = [survey for survey in df_features.strata_short]

#build xml file and push to AGOL
with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".xml") as temp_file:
  
  for survey_short in survey_names:
  
    #use metadata template (already has correct parent and child elements to fulfill metadata requirements)
    metadata_xml = "python/ARCGIS_METADATA_TEMPLATE.xml"
    
    #import xml and get xml roots
    tree = ET.parse(metadata_xml)
    root = tree.getroot()

    # filter df_features for survey
    result = df_features.query("strata_short == @survey_short")
  
    # extract metadata values
    if not result.empty:
      title = result.survey_name.iloc[0]
      abstract = result.abstract.iloc[0]
      purpose = result.purpose.iloc[0]
      tags = result.tags.iloc[0].split(', ')
      credits = result.useterms.iloc[0]
      pub_date = result.publish_date.iloc[0]
      meta_contact = result.meta_contact_name.iloc[0]
      meta_title = result.meta_contact_title.iloc[0]
      meta_email = result.meta_contact_email.iloc[0]
      source = result.source.iloc[0]
      useterms = result.useterms.iloc[0]
      link = result.link.iloc[0]
      extent_n = result.geoextent_n.iloc[0]
      extent_s = result.geoextent_s.iloc[0]
      extent_e = result.geoextent_e.iloc[0]
      extent_w = result.geoextent_w.iloc[0]
      rest_url = result.rest_url.iloc[0]
      file_ID = result.file_id.iloc[0]
      thumbnail = result.thumbnail.iloc[0]
      # convert thumbnail to base 64 encoded
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
    #change datetime to string
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

# layer info from smit_meta_layers
sql_query = "SELECT table_name, strata_short, abstract, rest_url FROM mdeb_spatial.smit_meta_layers"
df_layers = pd.read_sql(sql_query, con = connection)

#loop through surveys
for survey_short in survey_names:
  
  # grab file_id, rest_url by survey
  layerID = df_features.query("strata_short == @survey_short").file_id.iloc[0]
  
  item = gis.content.get(layerID)
  
  survey_layer = df_layers.query("strata_short == @survey_short")
  for index, row in survey_layer.iterrows():
    try:
      description = row['abstract'] if row['abstract'] is not None else ''
      layer_properties = {
        "description" : description,
        "licenseInfo" : item.licenseInfo,
        "copyrightText": item.licenseInfo
        } 
      feature_layer = FeatureLayer(row['rest_url'])
      print(f"{row['table_name']} layer exists, proceeding with update...")
      feature_layer.manager.update_definition(layer_properties)
      print(f"{row['rest_url']} layer updated successfully!")
    except Exception:
      print(f"layer {row['rest_url']} does not exist or could not be retrieved.") 
      
print("All layer level metadata updated!")