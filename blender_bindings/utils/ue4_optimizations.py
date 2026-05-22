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

    material_groups = {}
    for obj in brush_objects:
        if len(obj.material_slots) > 0 and obj.material_slots[0].material:
            mat_name = obj.material_slots[0].material.name
            if mat_name not in material_groups:
                material_groups[mat_name] = []
            material_groups[mat_name].append(obj)

    print(f"[+] Found {len(material_groups)} unique brush material groups.")
    
    # Save original selection/active state
    orig_active = bpy.context.view_layer.objects.active
    orig_selected = list(bpy.context.selected_objects)

    for mat_name, objs in material_groups.items():
        if len(objs) < 2:
            continue
            
        bpy.ops.object.select_all(action='DESELECT')
        for obj in objs:
            obj.select_set(True)
            
        bpy.context.view_layer.objects.active = objs[0]
        
        # Join objects
        try:
            bpy.ops.object.join()
            coalesced_obj = bpy.context.view_layer.objects.active
            coalesced_obj.name = f"Coalesced_Brush_{mat_name}"
            
            # Enter edit mode to clean double vertices & generate lightmap UVs
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.remove_doubles()
            
            # Create LightmapUV layer if needed
            uv_maps = coalesced_obj.data.uv_layers
            if len(uv_maps) < 2:
                uv_maps.new(name="LightmapUV")
                
            uv_maps["LightmapUV"].active = True
            bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.02)
            uv_maps[0].active = True
            
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception as e:
            print(f"[-] Failed to coalesce group {mat_name}: {e}")
            if bpy.context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

    # Restore selection/active state
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
            is_collision_volume = False
            for slot in obj.material_slots:
                if slot.material:
                    mat_name = slot.material.name.lower()
                    if "clip" in mat_name or "trigger" in mat_name or "collision" in mat_name:
                        is_collision_volume = True
                        break
            
            if is_collision_volume:
                if not obj.name.startswith("UCX_"):
                    obj.name = f"UCX_{obj.name}"
                    collision_count += 1
                    
    print(f"[+] Converted {collision_count} volumes to UE4-compatible collision meshes (UCX_ prefix).")

def run_ue4_optimizations(master_col):
    """Runs all optimizations to prepare the imported map for Unreal Engine 4 / Datasmith"""
    print("[+] Beginning UE4/Datasmith Map Import Optimizations...")
    process_skybox_scaling(master_col)
    optimize_brush_geometry(master_col)
    convert_triggers_to_collisions(master_col)
    print("[+] UE4/Datasmith Map Import Optimizations completed successfully!")
