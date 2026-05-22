import bpy

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
    
    # Identify skybox geometry by finding meshes clustered around sky_camera
    sky_objs = []
    for obj in master_col.all_objects:
        if obj.type == 'MESH' and obj != sky_camera:
            dist = (obj.location - sky_origin).length
            if dist < 3000.0:
                sky_objs.append(obj)
                
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
        for col in list(obj.users_collection):
            col.objects.unlink(obj)
        skybox_col.objects.link(obj)
        
        # Scale and position
        rel_loc = obj.location - sky_origin
        obj.location = rel_loc * scale_factor
        obj.scale = obj.scale * scale_factor
        
        # Tag metadata for Unreal post-import
        obj["is_skybox_geom"] = True
        obj["original_sky_camera_origin"] = [sky_origin.x, sky_origin.y, sky_origin.z]
        obj["skybox_scale_factor"] = scale_factor

    print("[+] 3D Skybox scaling and alignment optimization complete.")

def convert_triggers_to_collisions(master_col):
    """
    Renames specialized triggers and clip brush entities to 'UCX_' prefix 
    for automatic collision hull creation in UE4.
    
    CRITICAL: Excludes worldspawn and renderable world geometry (func_detail) 
    to prevent the level meshes from being imported as invisible collision blocks.
    """
    print("[+] Checking for trigger and clip volume conversions...")
    collision_count = 0
    
    # Names of entities that are purely collision/trigger and should not render
    COLLISION_SIGNATURES = ["trigger_", "func_clip", "func_brush_clip"]
    
    for obj in master_col.all_objects:
        if obj.type == 'MESH':
            # Skip core level structures (worldspawn) and detail geometry
            obj_name_lower = obj.name.lower()
            if "worldspawn" in obj_name_lower or "func_detail" in obj_name_lower:
                continue
                
            # Check if this object represents a trigger/clip entity or is explicitly tagged
            is_collision_entity = any(sig in obj_name_lower for sig in COLLISION_SIGNATURES)
            
            # Fallback check on material shaders if name is generic but entity type matches
            if not is_collision_entity and obj.get("entity_data"):
                classname = obj["entity_data"].get("classname", "").lower()
                is_collision_entity = any(sig in classname for sig in COLLISION_SIGNATURES)
            
            if is_collision_entity:
                if not obj.name.startswith("UCX_"):
                    obj.name = f"UCX_{obj.name}"
                    collision_count += 1
                    
    print(f"[+] Converted {collision_count} volumes to UE4-compatible collision meshes (UCX_ prefix).")

def run_ue4_optimizations(master_col):
    """Runs all optimizations to prepare the imported map for Unreal Engine 4 / Datasmith"""
    print("[+] Beginning UE4/Datasmith Map Import Optimizations...")
    process_skybox_scaling(master_col)
    convert_triggers_to_collisions(master_col)
    print("[+] UE4/Datasmith Map Import Optimizations completed successfully!")
