#this code is for connecting to arcgis.com via the ArcGIS API for python
#refer to https://github.com/Esri/arcgis-python-api for source code
#Further documentation at https://developers.arcgis.com/python/latest/

#IMPORT LIBRARIES
import arcpy
import arcgis
from arcgis.gis import GIS
from arcgis.features import FeatureLayer
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import Polygon

#log into arcgis online
#see documentation for logging in with various authentication schemes 
#https://developers.arcgis.com/python/latest/guide/working-with-different-authentication-schemes/
user = "" #enter arcgis.com username
password = "" #enter arcgis.com password
portal = "https://noaa.maps.arcgis.com/"
gis = GIS(portal, user, password)

#alternatively, log in using ArcGIS Pro, if Pro is on system computer and is logged into the portal
gis = GIS("PRO")

#test arcis.com connection
if gis is not None and gis._portal.is_logged_in:
  print(f"Successfully logged in as: {gis.properties.user['username']}")
else:
  print("Login failed.")

#EXAMPLE MAP
#pull data from arcgis online using feature server url, from ArcGIS REST API
#In this example, taking the World Continents feature layer from Living Atlas 
item_url = "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/World_Continents/FeatureServer/0"

#retrieve item from arcgis online
world_layer = FeatureLayer(item_url)

#query feature layer to return all data
world_features = world_layer.query(where="1=1")

#create a list to hold the geometries
geometries = []

#loop through features to extract geometries
for feature in world_features.features:
  geom = feature.geometry
  if geom['rings']:
    for ring in geom['rings']:
      polygon = Polygon(ring)
      geometries.append(polygon)

#create geopandas dataframe
gdf = gpd.GeoDataFrame(geometry=geometries)

#create map using geopandas
fig,ax = plt.subplots(figsize=(10,6))
gdf.plot(ax=ax, color='#D1E7DD', edgecolor='black')
plt.title('World Map')
ax.set_xticks([]) #remove tick marks
ax.set_yticks([])
ax.xaxis.set_ticklabels([]) #remove tick labels
ax.yaxis.set_ticklabels([])
plt.show()
