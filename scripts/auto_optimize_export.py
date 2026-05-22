import sys
import os
import json
import math
from pathlib import Path
import bpy

# Set up paths for SourceIO imports
addon_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(addon_dir))

from library.shared.content_providers.content_manager import ContentManager
from library.utils import FileBuffer
from blender_bindings.source1.bsp.import_bsp import import_bsp
from blender_bindings.operators.import_settings_base import Source1BSPSettings

class CustomImportSettings(Source1BSPSettings):
    def __init__(self):
        self.import_entities = True
        self.import_lightmapped_to_principled = True
        self.import_materials = True
        self.import_decals = True
        self.import_disp = True
        self.import_overlays = True
        self.scale = 1.0  # Keep 1.0 Hammer unit scale for precision, scale in UE4 import
        self.light_scale = 1.0

def find_skybox_objects(sky_camera_obj, master_col):
    """
    Identifies skybox objects. In Source maps, skybox geometry is either placed in
    a specific skybox collection or is geographically clustered far away near the sky_camera.
    """
    sky_objects = []
    sky_origin = sky_camera_obj.location
    
    # 1. Search by collection name
    for col in bpy.data.collections:
        if "skybox" in col.name.lower():
            for obj in col.objects:
                if obj.type == 'MESH':
                    sky_objects.append(obj)
            return sky_objects

    # 2. Fallback: Search for meshes clustered around the sky_camera (e.g., within 2000 Units)
    for obj in master_col.all_objects:
        if obj.type == 'MESH' and obj != sky_camera_obj:
            dist = (obj.location - sky_origin).length
            # Skybox geometry is typically tightly clustered around the sky_camera
            if dist < 3000.0:
                sky_objects.append(obj)
                
    return sky_objects

def process_skybox_scaling(master_col):
    """
    Automates scaling the 1/16th scale 3D skybox up to 1:1 scale
    and translates it to align with the main map coordinates.
    """
    # 1. Find sky_camera entity
    sky_camera = None
    for obj in bpy.data.objects:
        if "sky_camera" in obj.name or (obj.get("entity_data") and obj["entity_data"].get("classname") == "sky_camera"):
            sky_camera = obj
            break
            
    if not sky_camera:
        print("[-] No sky_camera found. Skipping 3D Skybox scaling optimization.")
        return

    entity_data = sky_camera.get("entity_data", {})
    scale_factor = float(entity_data.get("scale", 16.0)) or 16.0
    sky_origin = sky_camera.location
    
    print(f"[+] Found Sky Camera at {sky_origin} with Scale Factor {scale_factor}x")
    
    # Identify skybox geometry
    sky_objs = find_skybox_objects(sky_camera, master_col)
    if not sky_objs:
        print("[-] No skybox geometry detected around the sky camera.")
        return

    # Create a dedicated skybox collection
    skybox_col = bpy.data.collections.get("3D_Skybox_Optimized")
    if not skybox_col:
        skybox_col = bpy.data.collections.new("3D_Skybox_Optimized")
        bpy.context.scene.collection.children.link(skybox_col)

    print(f"[+] Optimizing and scaling {len(sky_objs)} skybox objects...")
    
    for obj in sky_objs:
        # Unlink from original collections and link to dedicated skybox collection
        for col in obj.users_collection:
            col.objects.unlink(obj)
        skybox_col.objects.link(obj)
        
        # 1. Store relative location to sky_camera
        rel_loc = obj.location - sky_origin
        
        # 2. Scale relative translation by scale factor
        scaled_loc = rel_loc * scale_factor
        
        # 3. Apply transformation
        obj.location = scaled_loc
        obj.scale = obj.scale * scale_factor
        
        # Add metadata tag so UE4 post-import script knows it's skybox geometry
        obj["is_skybox_geom"] = True
        obj["original_sky_camera_origin"] = [sky_origin.x, sky_origin.y, sky_origin.z]
        obj["skybox_scale_factor"] = scale_factor

    print("[+] 3D Skybox scaling and alignment optimization complete.")

def optimize_brush_geometry(master_col):
    """
    Coalesces adjacent brush faces sharing identical materials to optimize draw calls,
    and sets up secondary UV channel for UE4 lightmass baking.
    """
    print("[+] Running Brush Geometry Coalescence and UV optimization...")
    brush_objects = []
    
    for obj in master_col.all_objects:
        if obj.type == 'MESH' and ("brush" in obj.name.lower() or "worldspawn" in obj.name.lower()):
            brush_objects.append(obj)
            
    if not brush_objects:
        print("[-] No brush mesh objects found to optimize.")
        return

    # Group brushes by material to coalesce
    material_groups = {}
    for obj in brush_objects:
        if len(obj.material_slots) > 0 and obj.material_slots[0].material:
            mat_name = obj.material_slots[0].material.name
            if mat_name not in material_groups:
                material_groups[mat_name] = []
            material_groups[mat_name].append(obj)

    print(f"[+] Found {len(material_groups)} unique brush material groups.")
    
    for mat_name, objs in material_groups.items():
        if len(objs) < 2:
            continue
            
        # Select all objects in this group
        bpy.ops.object.select_all(action='DESELECT')
        for obj in objs:
            obj.select_set(True)
            
        # Set active object
        bpy.context.view_layer.objects.active = objs[0]
        
        # Coalesce: Join into a single mesh
        bpy.ops.object.join()
        coalesced_obj = bpy.context.view_layer.objects.active
        coalesced_obj.name = f"Coalesced_Brush_{mat_name}"
        
        # Enter edit mode to clean double vertices & generate lightmap UVs
        bpy.ops.object.mode_set(mode='EDIT')
        
        # Clean double vertices
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles()
        
        # Create secondary UV Map channel for Lightmaps (UVChannel_1 in UE4)
        uv_maps = coalesced_obj.data.uv_layers
        if len(uv_maps) < 2:
            uv_maps.new(name="LightmapUV")
            
        # Set LightmapUV active for unwrapping
        uv_maps["LightmapUV"].active = True
        
        # Smart UV Project for clean non-overlapping lightmaps
        bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.02)
        
        # Restore primary UV layout as active
        uv_maps[0].active = True
        
        bpy.ops.object.mode_set(mode='OBJECT')

    print("[+] Brush Geometry Coalescence and Lightmap UV generation complete.")

def convert_triggers_to_collisions(master_col):
    """
    Renames triggers and clip brushes to UE4 standard 'UCX_' prefix 
    for automatic collision hull creation on import.
    """
    print("[+] Checking for trigger and clip volume conversions...")
    collision_count = 0
    
    for obj in master_col.all_objects:
        if obj.type == 'MESH':
            # Check materials for toolsclip or toolstrigger signatures
            is_collision_volume = False
            for slot in obj.material_slots:
                if slot.material:
                    mat_name = slot.material.name.lower()
                    if "clip" in mat_name or "trigger" in mat_name or "collision" in mat_name:
                        is_collision_volume = True
                        break
            
            if is_collision_volume:
                # Prefix with UCX_ (Convex Collision) for Datasmith/FBX importer to build collisions
                if not obj.name.startswith("UCX_"):
                    obj.name = f"UCX_{obj.name}"
                    collision_count += 1
                    
    print(f"[+] Converted {collision_count} volumes to UE4-compatible collision meshes (UCX_ prefix).")

def run_import_and_optimize(bsp_path_str, mount_dir_str=None):
    bsp_path = Path(bsp_path_str)
    
    # Initialize Steam mounts/content manager
    content_manager = ContentManager()
    if mount_dir_str:
        content_manager.scan_for_content(Path(mount_dir_str))
    else:
        content_manager.scan_for_content(bsp_path)

    print(f"[+] Importing BSP Map: {bsp_path.name}")
    
    # Import map
    settings = CustomImportSettings()
    with FileBuffer(bsp_path) as f:
        import_bsp(bsp_path, f, content_manager, settings)
        
    master_col = bpy.data.collections.get(bsp_path.name)
    if not master_col:
        print("[-] Master collection not found after import.")
        return
        
    # --- Execute optimizations ---
    process_skybox_scaling(master_col)
    optimize_brush_geometry(master_col)
    convert_triggers_to_collisions(master_col)
    
    print("[+] All Phase 1 import optimizations finished successfully!")

if __name__ == "__main__":
    # Example usage inside Blender:
    # blender --background --python auto_optimize_export.py -- <bsp_path> [mount_dir]
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(args) >= 1:
        bsp_path = args[0]
        mount_dir = args[1] if len(args) > 1 else None
        run_import_and_optimize(bsp_path, mount_dir)
    else:
        print("[-] Please supply a BSP file path. E.g. blender --python auto_optimize_export.py -- <path_to_bsp>")
