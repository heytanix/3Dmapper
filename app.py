import os
import tempfile
import json
import math
import requests
from flask import Flask, render_template, request, send_file, jsonify
from shapely.geometry import Polygon
from PIL import Image
import io

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

def get_osm_buildings(bbox):
    """Fetch building data from Overpass API"""
    overpass_url = "http://overpass-api.de/api/interpreter"
    
    overpass_query = f"""
    [out:json][timeout:60];
    (
      way["building"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
      relation["building"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
    );
    out geom;
    """
    
    try:
        response = requests.post(overpass_url, data={'data': overpass_query}, timeout=60)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise Exception(f"Failed to fetch OSM data: {str(e)}")

def long2tile(lon, zoom):
    """Convert longitude to tile X coordinate"""
    return int((lon + 180) / 360 * (2 ** zoom))

def lat2tile(lat, zoom):
    """Convert latitude to tile Y coordinate"""
    lat_rad = math.radians(lat)
    return int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * (2 ** zoom))

def tile2long(x, zoom):
    """Convert tile X to longitude"""
    return x / (2 ** zoom) * 360.0 - 180.0

def tile2lat(y, zoom):
    """Convert tile Y to latitude"""
    n = math.pi - 2 * math.pi * y / (2 ** zoom)
    return math.degrees(math.atan(math.sinh(n)))

def get_tiles_for_bbox(bbox, zoom):
    """Get all tiles covering the bounding box"""
    west, south, east, north = bbox
    
    min_x = long2tile(west, zoom)
    max_x = long2tile(east, zoom)
    min_y = lat2tile(north, zoom)  # Y is flipped
    max_y = lat2tile(south, zoom)
    
    return min_x, min_y, max_x, max_y

def download_and_stitch_tiles(min_x, min_y, max_x, max_y, zoom, tile_size=256):
    """Download tiles and stitch them into one image"""
    width = (max_x - min_x + 1) * tile_size
    height = (max_y - min_y + 1) * tile_size
    
    # Create blank canvas
    stitched_image = Image.new('RGB', (width, height), (240, 240, 240))
    
    # Download and place each tile
    for tile_x in range(min_x, max_x + 1):
        for tile_y in range(min_y, max_y + 1):
            tile_url = f"https://tile.openstreetmap.org/{zoom}/{tile_x}/{tile_y}.png"
            
            try:
                response = requests.get(tile_url, 
                                      headers={'User-Agent': 'OSM 3D Map Exporter/1.0'},
                                      timeout=10)
                response.raise_for_status()
                
                # Open tile image
                tile_image = Image.open(io.BytesIO(response.content))
                
                # Calculate position in stitched image
                pos_x = (tile_x - min_x) * tile_size
                pos_y = (tile_y - min_y) * tile_size
                
                # Paste tile
                stitched_image.paste(tile_image, (pos_x, pos_y))
                
            except Exception as e:
                print(f"Failed to download tile {tile_x}/{tile_y}: {e}")
                # Fill with light gray if download fails
                tile_image = Image.new('RGB', (tile_size, tile_size), (220, 220, 220))
                pos_x = (tile_x - min_x) * tile_size
                pos_y = (tile_y - min_y) * tile_size
                stitched_image.paste(tile_image, (pos_x, pos_y))
    
    return stitched_image

def crop_image_to_exact_bbox(stitched_image, user_bbox, tiles_bbox, zoom, tile_size=256):
    """Crop stitched image to exact user bounding box"""
    user_west, user_south, user_east, user_north = user_bbox
    tiles_west, tiles_south, tiles_east, tiles_north = tiles_bbox
    
    # Calculate image dimensions
    image_width = stitched_image.width
    image_height = stitched_image.height
    
    # Calculate pixel positions of user bbox within stitched image
    # X calculation
    x_ratio = (user_west - tiles_west) / (tiles_east - tiles_west)
    crop_left = int(x_ratio * image_width)
    
    x_ratio = (user_east - tiles_west) / (tiles_east - tiles_west)
    crop_right = int(x_ratio * image_width)
    
    # Y calculation (note: image Y is flipped)
    y_ratio = (tiles_north - user_north) / (tiles_north - tiles_south)
    crop_top = int(y_ratio * image_height)
    
    y_ratio = (tiles_north - user_south) / (tiles_north - tiles_south)
    crop_bottom = int(y_ratio * image_height)
    
    # Ensure valid crop bounds
    crop_left = max(0, min(crop_left, image_width-1))
    crop_right = max(crop_left+1, min(crop_right, image_width))
    crop_top = max(0, min(crop_top, image_height-1))
    crop_bottom = max(crop_top+1, min(crop_bottom, image_height))
    
    # Crop the image
    cropped_image = stitched_image.crop((crop_left, crop_top, crop_right, crop_bottom))
    
    return cropped_image

def get_perfect_map_texture(user_bbox, target_size=512):
    """Get perfectly aligned map texture for the exact user bounding box"""
    
    # Choose zoom level based on bbox size
    west, south, east, north = user_bbox
    bbox_width = east - west
    bbox_height = north - south
    max_dimension = max(bbox_width, bbox_height)
    
    if max_dimension > 0.01:  # > ~1km
        zoom = 14
    elif max_dimension > 0.005:  # > ~500m
        zoom = 15
    else:
        zoom = 16
    
    # Get tiles covering the bbox
    min_x, min_y, max_x, max_y = get_tiles_for_bbox(user_bbox, zoom)
    
    # Calculate the bounding box of the tile grid
    tiles_west = tile2long(min_x, zoom)
    tiles_east = tile2long(max_x + 1, zoom)
    tiles_north = tile2lat(min_y, zoom)
    tiles_south = tile2lat(max_y + 1, zoom)
    tiles_bbox = (tiles_west, tiles_south, tiles_east, tiles_north)
    
    # Download and stitch tiles
    stitched_image = download_and_stitch_tiles(min_x, min_y, max_x, max_y, zoom)
    
    # Crop to exact user bbox
    cropped_image = crop_image_to_exact_bbox(stitched_image, user_bbox, tiles_bbox, zoom)
    
    # Resize to target size while maintaining aspect ratio
    cropped_image = cropped_image.resize((target_size, target_size), Image.LANCZOS)
    
    return cropped_image

def lat_lon_to_meters(lat, lon, origin_lat, origin_lon):
    """Convert lat/lon to local meter coordinates"""
    R = 6378137  # Earth radius in meters
    
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    origin_lat_rad = math.radians(origin_lat)
    origin_lon_rad = math.radians(origin_lon)
    
    x = R * (lon_rad - origin_lon_rad) * math.cos(origin_lat_rad)
    y = R * (lat_rad - origin_lat_rad)
    
    return x, y

def create_perfect_ground_plane(bbox, map_image_path):
    """Create perfectly aligned ground plane"""
    west, south, east, north = bbox
    
    # Calculate origin
    origin_lat = (south + north) / 2
    origin_lon = (west + east) / 2
    
    # Convert bbox corners to meters
    sw_x, sw_y = lat_lon_to_meters(south, west, origin_lat, origin_lon)
    se_x, se_y = lat_lon_to_meters(south, east, origin_lat, origin_lon)
    nw_x, nw_y = lat_lon_to_meters(north, west, origin_lat, origin_lon)
    ne_x, ne_y = lat_lon_to_meters(north, east, origin_lat, origin_lon)
    
    obj_lines = [
        "# Perfect Aligned Ground Plane",
        f"# Bbox: {bbox}",
        f"# Origin: {origin_lat:.6f}, {origin_lon:.6f}",
        "",
        "# Ground vertices",
        f"v {sw_x:.3f} {sw_y:.3f} -0.1",  # 1: Southwest
        f"v {se_x:.3f} {se_y:.3f} -0.1",  # 2: Southeast
        f"v {ne_x:.3f} {ne_y:.3f} -0.1",  # 3: Northeast
        f"v {nw_x:.3f} {nw_y:.3f} -0.1",  # 4: Northwest
        "",
        "# UV coordinates",
        "vt 0.0 0.0",  # 1: Southwest UV
        "vt 1.0 0.0",  # 2: Southeast UV
        "vt 1.0 1.0",  # 3: Northeast UV
        "vt 0.0 1.0",  # 4: Northwest UV
        "",
        "usemtl ground_texture",
        "g ground_plane",
        "# Two triangles forming the ground rectangle",
        "f 1/1 2/2 3/3",  # Southwest-Southeast-Northeast
        "f 1/1 3/3 4/4",  # Southwest-Northeast-Northwest
        ""
    ]
    
    return obj_lines, 4

def create_building_geometry(elements, origin_lat, origin_lon, building_height, quality):
    """Create building geometry with same coordinate system as ground"""
    obj_lines = ["# Buildings positioned on perfect ground"]
    vertex_count = 4  # After ground plane
    building_count = 0
    
    simplification_tolerance = {'low': 2.0, 'medium': 1.0, 'high': 0.3}.get(quality, 1.0)
    min_area_threshold = {'low': 25.0, 'medium': 10.0, 'high': 5.0}.get(quality, 10.0)
    
    for element in elements:
        if not (element.get('tags', {}).get('building') and 'geometry' in element):
            continue
            
        coords = [(node['lon'], node['lat']) for node in element['geometry']]
        if len(coords) < 4:
            continue
            
        if coords[0] == coords[-1]:
            coords = coords[:-1]
        if len(coords) < 3:
            continue
        
        try:
            # Convert using SAME origin as ground plane
            local_coords = []
            for lon, lat in coords:
                x, y = lat_lon_to_meters(lat, lon, origin_lat, origin_lon)
                local_coords.append((x, y))
            
            polygon = Polygon(local_coords)
            if not polygon.is_valid or polygon.area < min_area_threshold:
                continue
            
            # Simplify
            simplified = polygon.simplify(simplification_tolerance, preserve_topology=True)
            if simplified.geom_type == 'Polygon':
                simplified_coords = list(simplified.exterior.coords)[:-1]
            else:
                simplified_coords = local_coords
            
            if len(simplified_coords) < 3:
                continue
            
            # Get height
            tags = element.get('tags', {})
            height = building_height
            
            if 'building:height' in tags:
                try:
                    height = max(float(tags['building:height'].replace('m', '').replace(' ', '')), 2.0)
                except:
                    pass
            elif 'building:levels' in tags:
                try:
                    levels = int(tags['building:levels'])
                    height = max(levels * 3.5, 2.0)
                except:
                    pass
            
            # Create vertices
            base_vertices = []
            top_vertices = []
            
            for x, y in simplified_coords:
                obj_lines.append(f"v {x:.3f} {y:.3f} 0.0")
                base_vertices.append(vertex_count + 1)
                vertex_count += 1
                
                obj_lines.append(f"v {x:.3f} {y:.3f} {height:.3f}")
                top_vertices.append(vertex_count + 1)
                vertex_count += 1
            
            building_count += 1
            obj_lines.append(f"g building_{building_count}")
            obj_lines.append("usemtl building_material")
            
            n = len(simplified_coords)
            
            # Bottom face
            face_indices = [str(base_vertices[i]) for i in reversed(range(n))]
            obj_lines.append(f"f {' '.join(face_indices)}")
            
            # Top face
            face_indices = [str(top_vertices[i]) for i in range(n)]
            obj_lines.append(f"f {' '.join(face_indices)}")
            
            # Walls
            for i in range(n):
                next_i = (i + 1) % n
                v1 = base_vertices[i]
                v2 = base_vertices[next_i]
                v3 = top_vertices[next_i]
                v4 = top_vertices[i]
                obj_lines.append(f"f {v1} {v2} {v3} {v4}")
                
        except Exception:
            continue
    
    return obj_lines, vertex_count, building_count

def create_material_file(texture_filename):
    """Create MTL file"""
    return f"""# Perfect Aligned Materials

newmtl ground_texture
Ka 1.0 1.0 1.0
Kd 1.0 1.0 1.0
Ks 0.0 0.0 0.0
map_Kd {texture_filename}

newmtl building_material
Ka 0.7 0.7 0.7
Kd 0.8 0.8 0.8
Ks 0.2 0.2 0.2
Ns 20.0
"""

@app.route('/export_obj', methods=['POST'])
def export_obj():
    data = request.json
    bbox = data.get('bbox')  # [west, south, east, north]
    building_height = data.get('building_height', 10)
    quality = data.get('quality', 'medium')
    
    if not bbox or len(bbox) != 4:
        return jsonify({'error': 'Invalid bounding box'}), 400
    
    west, south, east, north = bbox
    if west >= east or south >= north:
        return jsonify({'error': 'Invalid bounding box coordinates'}), 400
    
    area_deg = (east - west) * (north - south)
    if area_deg > 0.01:
        return jsonify({'error': 'Selected area too large. Please select smaller area.'}), 400
    
    try:
        # Get buildings for exact bbox
        osm_data = get_osm_buildings(bbox)
        elements = osm_data.get('elements', [])
        building_elements = [e for e in elements if e.get('tags', {}).get('building')]
        
        if not building_elements:
            return jsonify({'error': 'No buildings found in selected area.'}), 404
        
        # Create temp directory
        temp_dir = tempfile.mkdtemp()
        
        # Get perfect map texture for exact bbox
        map_image = get_perfect_map_texture(bbox)
        texture_filename = "perfect_map.png"
        texture_path = os.path.join(temp_dir, texture_filename)
        map_image.save(texture_path, 'PNG')
        
        # Use same origin for everything
        origin_lat = (south + north) / 2
        origin_lon = (west + east) / 2
        
        # Create OBJ
        obj_lines = [
            "# Perfect Aligned 3D Map",
            f"# User bbox: {south:.6f},{west:.6f} to {north:.6f},{east:.6f}",
            f"# Origin: {origin_lat:.6f}, {origin_lon:.6f}",
            "",
            "mtllib perfect_materials.mtl",
            ""
        ]
        
        # Ground plane
        ground_lines, ground_vertices = create_perfect_ground_plane(bbox, texture_filename)
        obj_lines.extend(ground_lines)
        
        # Buildings
        building_lines, total_vertices, building_count = create_building_geometry(
            building_elements, origin_lat, origin_lon, building_height, quality)
        obj_lines.extend(building_lines)
        
        # Save OBJ
        obj_filename = f"perfect_3d_map_{south:.4f}_{west:.4f}.obj"
        obj_path = os.path.join(temp_dir, obj_filename)
        with open(obj_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(obj_lines))
        
        # Create MTL
        mtl_content = create_material_file(texture_filename)
        mtl_path = os.path.join(temp_dir, "perfect_materials.mtl")
        with open(mtl_path, 'w', encoding='utf-8') as f:
            f.write(mtl_content)
        
        # Create ZIP
        import zipfile
        zip_filename = f"perfect_3d_map_{south:.4f}_{west:.4f}.zip"
        zip_path = os.path.join(temp_dir, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            zipf.write(obj_path, obj_filename)
            zipf.write(mtl_path, "perfect_materials.mtl")
            zipf.write(texture_path, texture_filename)
        
        return send_file(
            zip_path,
            as_attachment=True,
            download_name=zip_filename,
            mimetype='application/zip'
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            import shutil
            if 'temp_dir' in locals():
                shutil.rmtree(temp_dir)
        except:
            pass

if __name__ == '__main__':
    app.run(debug=True, port=5000)