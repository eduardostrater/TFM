
# Librerías base
import json

def show_area(value):
    print(f"Área: {value/1e6:.2f} km²")


def simplifica_coordenadas(coords, decimals=3):
        """Reduce la precisión de coordenadas para reducir tamaño del GeoJSON.
        3 decimales = ~111 metros de precisión """
        if isinstance(coords, (list, tuple)):
            if len(coords) > 0:
                # Si es una coordenada [lon, lat]
                if isinstance(coords[0], (int, float)):
                    return [round(c, decimals) for c in coords]
                # Si es una lista de coordenadas
                else:
                    return [simplifica_coordenadas(c, decimals) for c in coords]
        return coords



# Aplicar simplificación a diferentes tipos de geometría
def simplifica_geografias(geojson):
    if isinstance(geojson, dict):
        if geojson.get('type') == 'FeatureCollection':
            features = geojson.get('features', [])
            if features:
                first_feature = features[0]
                geometry = first_feature.get('geometry')
                if geometry:
                    # Simplificar coordenadas
                    simplified_geom = {
                        'type': geometry.get('type'),
                        'coordinates': simplifica_coordenadas(geometry.get('coordinates'))
                    }
                    
                    size_after = len(json.dumps(simplified_geom))
  
                    return simplified_geom
                    
        elif geojson.get('type') == 'Feature':
            geometry = geojson.get('geometry')
            if geometry:
                simplified_geom = {
                    'type': geometry.get('type'),
                    'coordinates': simplifica_coordenadas(geometry.get('coordinates'))
                }
                
                size_after = len(json.dumps(simplified_geom))
 
                return simplified_geom
                
        elif geojson.get('type') == 'GeometryCollection':
            # NUEVO: Manejar GeometryCollection extrayendo el polígono más grande
            geometries = geojson.get('geometries', [])
            largest_polygon = None
            largest_area = 0
            
            for geom in geometries:
                geom_type = geom.get('type')
                if geom_type in ['Polygon', 'MultiPolygon']:
                    # Estimar área contando coordenadas (proxy)
                    coords = geom.get('coordinates', [])
                    coords_count = sum(len(c) if isinstance(c, list) else 1 for c in str(coords))
                    if coords_count > largest_area:
                        largest_area = coords_count
                        largest_polygon = geom
            
            if largest_polygon:
                simplified_geom = {
                    'type': largest_polygon.get('type'),
                    'coordinates': simplifica_coordenadas(largest_polygon.get('coordinates'))
                }
                
                size_after = len(json.dumps(simplified_geom))
  
                return simplified_geom
            
        elif geojson.get('type') in ['Polygon', 'MultiPolygon', 'Point', 'LineString', 'MultiPoint', 'MultiLineString']:
            simplified_geom = {
                'type': geojson.get('type'),
                'coordinates': simplifica_coordenadas(geojson.get('coordinates'))
            }
            
            size_after = len(json.dumps(simplified_geom))
  
            return simplified_geom
        

def _extract_spanish_properties(properties: dict) -> dict:
    """Extrae solo propiedades en español de un diccionario de propiedades OSM."""
    spanish_props = {}
    spanish_keys = ['name', 'name:es', 'name_es', 'admin_level', 'boundary']
    
    for key in spanish_keys:
        if key in properties:
            spanish_props[key] = properties[key]
    
    return spanish_props
