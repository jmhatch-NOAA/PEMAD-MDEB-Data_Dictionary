#install the R-ArcGIS Bridge for the appropriate version of R at https://r.esri.com/bin/
#unzip and install package in r from packages>install from local file
#alternatively, you can install from github
#install.packages("arcgisbinding", repos = "https://r.esri.com", type = "win.binary")
#see https://developers.arcgis.com/r-bridge/installation/ for more documentation of R-Bridge for ArcGIS
#___________________________________________
#also install the arcgis metapackage, which is still in development and currently includes the arcgislayers and
#arcgisutils packages, see https://github.com/R-ArcGIS/arcgis for updates
#remotes::install_github("R-ArcGIS/arcgis")
#_________________________________________

#IMPORT LIBRARIES
#_____________________
library(arcgisbinding)
arc.check_product()
library(arcgislayers)
library(arcgisutils)
library(ggplot2)
library(sf)
#connect to arcgis online
arc.portal_connect(url =  "https://noaa.maps.arcgis.com", user = "",
                   password = "") #enter arcgis online username and password
arc.check_portal()

#examples on how to pull data from arcgis online
#_______________________________________________
#by using a feature layer or feature server url

#create an example map of USA using REST API Layer:USA Counties
#provide feature server url/feature layer
feature_server_url <- "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/TIGERweb_Counties_v1/FeatureServer/0"
#create a feature layer object
data <- arc_open(feature_server_url)
#query the feature layer and return the layer as an sf (simple feature) object
sf_data <- arc_select(data)

#create map from sf object
USA_map <- ggplot(data = sf_data)+
            geom_sf(fill = "white")+ #fill color white
            coord_sf(xlim= c(-13951910,-7000000), ylim = c(1000000, 7000000)) #set map coordinates (in meters)
