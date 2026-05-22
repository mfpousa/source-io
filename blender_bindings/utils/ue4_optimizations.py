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

def generate_lightmap_uv(obj):
    """
    Creates a non-overlapping secondary UV map channel named 'LightmapUV' 
    (equivalent to UV Channel 1 in Unreal Engine) and unwraps the geometry.
    """
    try:
        # Save selection state
        orig_active = bpy.context.view_layer.objects.active
        orig_selected = list(bpy.context.selected_objects)
        
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        
        uv_maps = obj.data.uv_layers
        # Unreal expects the lightmap coordinates in the 2nd channel (index 1)
        if len(uv_maps) < 2:
            uv_maps.new(name="LightmapUV")
            
        uv_maps["LightmapUV"].active = True
        
        # Enter edit mode and unwrap with smart project (ensures no overlaps)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.02)
        bpy.ops.object.mode_set(mode='OBJECT')
        
        # Keep primary texture UV active for standard material rendering
        uv_maps[0].active = True
        
        # Restore selection state
        bpy.ops.object.select_all(action='DESELECT')
        for o in orig_selected:
            try:
                o.select_set(True)
            except ReferenceError:
                pass
        if orig_active:
            try:
                bpy.context.view_layer.objects.active = orig_active
            except ReferenceError:
                pass
                
    except Exception as e:
        print(f"[-] Failed to generate Lightmap UV for {obj.name}: {e}")
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

def split_and_consolidate_static_geometry(master_col):
    """
    Spatially optimizes monolithic static world geometry (worldspawn, func_detail) and displacements:
    1. Splits world_geometry once by material (fast, reduces draw call slots to exactly 1).
    2. Combines these material parts with displacement terrain tiles (already separate).
    3. Groups all elements geographically into a 3D spatial grid (e.g., 15m grid cells).
    4. Re-merges (consolidates) localized pieces sharing the same material within each cell.
    5. Automatically generates non-overlapping secondary Lightmap UVs for UE4 baking.
    """
    world_geom_targets = []
    disp_targets = []
    
    for obj in master_col.all_objects:
        if obj.type == 'MESH' and not obj.name.startswith("UCX_"):
            name_lower = obj.name.lower()
            if "worldspawn" in name_lower or "world_geometry" in name_lower:
                world_geom_targets.append(obj)
            elif "_disp_" in name_lower:
                disp_targets.append(obj)

    if not world_geom_targets and not disp_targets:
        print("[-] No static world geometry or displacements found to optimize.")
        return

    print(f"[+] Optimizing {len(world_geom_targets)} world meshes and {len(disp_targets)} displacement tiles...")
    
    # Save original selection/active state
    orig_selected = list(bpy.context.selected_objects)
    orig_active = bpy.context.view_layer.objects.active

    objects_to_cluster = []

    # Phase 1: Split main world geometry target meshes by Material
    # This is extremely fast (< 1s) because we only enter/exit Edit Mode once per world mesh
    for target in world_geom_targets:
        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        bpy.context.view_layer.objects.active = target
        
        try:
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.separate(type='MATERIAL')
            bpy.ops.object.mode_set(mode='OBJECT')
            
            # Collect all material parts
            material_parts = [obj for obj in bpy.context.selected_objects if obj != target]
            objects_to_cluster.extend(material_parts)
            # Include the remaining main mesh itself (which holds the first material)
            objects_to_cluster.append(target)
        except Exception as e:
            print(f"[-] Error splitting target {target.name} by material: {e}")
            if bpy.context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            objects_to_cluster.append(target)

    # Displacements are already separate, single-material tiles, so we can group them directly!
    objects_to_cluster.extend(disp_targets)
    
    # Remove any dead references or non-meshes
    objects_to_cluster = list(set([obj for obj in objects_to_cluster if obj and obj.type == 'MESH']))
    print(f"[+] Processing {len(objects_to_cluster)} total optimized elements for spatial grouping.")

    # Phase 2: Spatial and Material Grid Grouping
    # 15.0 meters is roughly 650 Hammer units - a perfect room-scale culling size
    GRID_SIZE = 15.0 
    spatial_groups = {}

    for obj in objects_to_cluster:
        try:
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

    # Phase 3: Spatial Re-merging / Consolidation & UV Generation
    consolidated_count = 0
    uv_generation_count = 0
    
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

        if len(valid_objs) == 0:
            continue

        if len(valid_objs) == 1:
            # Standalone element: No merging needed, just generate Lightmap UV channel directly
            generate_lightmap_uv(valid_objs[0])
            uv_generation_count += 1
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
            
            # Rename cleanly
            mat_name, gx, gy, gz = grid_key
            merged_obj.name = f"Consolidated_{mat_name}_G_{gx}_{gy}_{gz}"
            consolidated_count += 1
            
            # Generate Lightmap UV channel for the consolidated mesh
            generate_lightmap_uv(merged_obj)
            uv_generation_count += 1
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

    print(f"[+] Spatial consolidation complete. Re-merged fragments into {consolidated_count} meshes.")
    print(f"[+] Lightmap UVs successfully generated for {uv_generation_count} static meshes!")

def run_ue4_optimizations(master_col):
    """Runs all optimizations to prepare the imported map for Unreal Engine 4 / Datasmith"""
    print("[SourceIO] Beginning UE4/Datasmith Map Import Optimizations...")
    
    # Force Blender to update and cache all newly linked objects and hierarchies
    bpy.context.view_layer.update()
    
    total_objects = len(master_col.all_objects)
    print(f"[SourceIO] Scanned master collection. Found {total_objects} total objects.")
    
    print("[SourceIO] Step 1: Processing Skybox scaling...")
    try:
        process_skybox_scaling(master_col)
    except Exception as e:
        import traceback
        print(f"[SourceIO] ERROR in process_skybox_scaling: {e}")
        traceback.print_exc()

    print("[SourceIO] Step 2: Processing static geometry splitting and consolidation...")
    try:
        split_and_consolidate_static_geometry(master_col)
    except Exception as e:
        import traceback
        print(f"[SourceIO] ERROR in split_and_consolidate_static_geometry: {e}")
        traceback.print_exc()

    print("[SourceIO] Step 3: Processing collision volume conversions...")
    try:
        convert_triggers_to_collisions(master_col)
    except Exception as e:
        import traceback
        print(f"[SourceIO] ERROR in convert_triggers_to_collisions: {e}")
        traceback.print_exc()
        
    print("[SourceIO] UE4/Datasmith Map Import Optimizations completed successfully!")
