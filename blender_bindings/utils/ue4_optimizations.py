import bpy
from mathutils import Vector

def get_bbox_center(obj):
    """Calculates the world-space center of an object's bounding box."""
    try:
        mw = obj.matrix_world
        return sum((mw @ Vector(corner) for corner in obj.bound_box), Vector()) / 8
    except Exception:
        return obj.location

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
    
    # Identify skybox geometry by finding meshes whose true geometry centers are clustered near the sky_camera.
    # We use a tight threshold of 100 Blender meters (~4350 Hammer units) because 3D skyboxes are small
    # and the main playable map is situated much further away.
    sky_objs = []
    for obj in master_col.all_objects:
        if obj.type == 'MESH' and obj != sky_camera:
            geom_center = get_bbox_center(obj)
            dist = (geom_center - sky_origin).length
            if dist < 100.0:
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
        
        # Scale and position relative to the sky origin
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

def split_and_consolidate_static_geometry(master_col):
    """
    Spatially optimizes monolithic static world geometry (worldspawn, func_detail):
    1. Splits massive meshes by material (reducing draw call slots to exactly 1).
    2. Splits them by loose parts to isolate individual room pieces.
    3. Groups pieces geographically into a 3D spatial grid (e.g. 15m grid cells).
    4. Re-merges (consolidates) localized pieces sharing the same material within each cell.
    """
    static_targets = []
    for obj in master_col.all_objects:
        if obj.type == 'MESH':
            name_lower = obj.name.lower()
            # Only optimize static structural geometry (worldspawn, func_detail)
            # Avoid interactive entities (doors, buttons, physics boxes)
            if ("worldspawn" in name_lower or "func_detail" in name_lower) and not obj.name.startswith("UCX_"):
                static_targets.append(obj)

    if not static_targets:
        print("[-] No static world geometry found to optimize.")
        return

    print(f"[+] Optimizing and spatially consolidating {len(static_targets)} static meshes...")
    
    # Save original selection/active state
    orig_selected = list(bpy.context.selected_objects)
    orig_active = bpy.context.view_layer.objects.active

    # Phase 1 & 2: Split target meshes by Material and then Loose Parts
    separated_pieces = []
    
    for target in static_targets:
        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        bpy.context.view_layer.objects.active = target
        
        # 1. Split by Material
        try:
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.separate(type='MATERIAL')
            bpy.ops.object.mode_set(mode='OBJECT')
            
            # Record resulting pieces
            material_parts = [obj for obj in bpy.context.selected_objects if obj != target]
            
            # 2. Split each material part by Loose Parts for spatial granularity
            for part in material_parts:
                bpy.ops.object.select_all(action='DESELECT')
                part.select_set(True)
                bpy.context.view_layer.objects.active = part
                
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.separate(type='LOOSE')
                bpy.ops.object.mode_set(mode='OBJECT')
                
                # Collect all loose fragments
                separated_pieces.extend(bpy.context.selected_objects)
        except Exception as e:
            print(f"[-] Error splitting target {target.name}: {e}")
            if bpy.context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

    # Remove duplicates from our list of pieces
    separated_pieces = list(set(separated_pieces))
    print(f"[+] Generated {len(separated_pieces)} raw spatial structural fragments.")

    # Phase 3: Spatial and Material Grid Grouping
    # 15.0 meters is roughly 650 Hammer units - a perfect room-scale culling size
    GRID_SIZE = 15.0 
    spatial_groups = {}

    for obj in separated_pieces:
        try:
            if not obj.type == 'MESH':
                continue
                
            # Find active material name
            mat_name = "NoMaterial"
            if len(obj.material_slots) > 0 and obj.material_slots[0].material:
                mat_name = obj.material_slots[0].material.name
                
            # Find true geographic coordinate center
            center = get_bbox_center(obj)
            
            # Determine 3D grid index
            grid_x = int(center.x // GRID_SIZE)
            grid_y = int(center.y // GRID_SIZE)
            grid_z = int(center.z // GRID_SIZE)
            
            grid_key = (mat_name, grid_x, grid_y, grid_z)
            
            if grid_key not in spatial_groups:
                spatial_groups[grid_key] = []
            spatial_groups[grid_key].append(obj)
        except ReferenceError:
            pass

    print(f"[+] Clustering fragments into {len(spatial_groups)} material-spatial cells...")

    # Phase 4: Spatial Re-merging / Consolidation
    consolidated_count = 0
    
    for grid_key, objs in spatial_groups.items():
        # Filter out reference-dead or already joined objects
        valid_objs = []
        for obj in objs:
            try:
                # Check if object is still valid and linked
                _ = obj.name
                valid_objs.append(obj)
            except ReferenceError:
                pass

        if len(valid_objs) < 2:
            continue

        bpy.ops.object.select_all(action='DESELECT')
        for obj in valid_objs:
            obj.select_set(True)
            
        bpy.context.view_layer.objects.active = valid_objs[0]
        
        # Merge pieces in this spatial grid cell using same material
        try:
            bpy.ops.object.join()
            merged_obj = bpy.context.view_layer.objects.active
            
            # Clean up welds
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.remove_doubles()
            bpy.ops.object.mode_set(mode='OBJECT')
            
            mat_name, gx, gy, gz = grid_key
            merged_obj.name = f"Consolidated_{mat_name}_G_{gx}_{gy}_{gz}"
            consolidated_count += 1
        except Exception as e:
            print(f"[-] Failed to consolidate grid cell {grid_key}: {e}")
            if bpy.context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

    # Restore original selection/active state
    bpy.ops.object.select_all(action='DESELECT')
    for obj in orig_selected:
        try:
            obj.select_set(True)
        except ReferenceError:
            pass
    if orig_active:
        try:
            bpy.context.view_layer.objects.active = orig_active
        except ReferenceError:
            pass

    print(f"[+] Spatial consolidation complete. Re-merged fragments into {consolidated_count} optimized, room-scale meshes!")

def run_ue4_optimizations(master_col):
    """Runs all optimizations to prepare the imported map for Unreal Engine 4 / Datasmith"""
    print("[+] Beginning UE4/Datasmith Map Import Optimizations...")
    process_skybox_scaling(master_col)
    split_and_consolidate_static_geometry(master_col)
    convert_triggers_to_collisions(master_col)
    print("[+] UE4/Datasmith Map Import Optimizations completed successfully!")
