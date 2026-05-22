# Source Engine to Unreal Engine 4 Map Porting Plan

This document outlines the complete hybrid pipeline for importing Source Engine maps into Unreal Engine 4 (UE4) using **SourceIO**, **Blender**, **Datasmith**, and **Post-Import Python Automation**.

---

## Phase 1: Blender Import, Cleanup, and Export

### 1.1 Import Map using SourceIO
- Open a clean Blender scene.
- Navigate to `File > Import > Source Engine Assets`.
- Import the compiled map format (`.BSP` for Source 1, or `.VMAP` for Source 2).
- *Result:* SourceIO imports meshes, retains their face-by-face material bindings, and places entities (`prop_static`, `prop_dynamic`, pickups, spawn points) as **linked duplicates** (instanced objects).

### 1.2 Optimize Brush Geometry (BSP Coalescence)
- **The Issue:** Every brush face or individual minor solid is imported as a separate mesh block, leading to an extreme draw-call count in UE4.
- **Automation Action:** Run a script to merge contiguous coplanar brush faces sharing identical materials.
- **Lightmap UVs:** Auto-unwrap these merged structures to **UV Channel 2** (Blender's secondary UV map) using Smart UV Project to allow UE4's Lightmass to bake high-fidelity lighting.

### 1.3 Export Scene using Datasmith
- Enable the **Datasmith Exporter** addon in Blender.
- Export the scene as a `.udatasmith` file.
- *Benefits:* Datasmith automatically respects SourceIO’s instancing, converting linked duplicates into shared static mesh assets and instances in Unreal, whilst preserving custom Hammer metadata inside Datasmith User Data.

---

## Phase 2: Unreal Engine 4 Import & Setup

### 2.1 Datasmith Import
- Open Unreal Engine 4.
- Click **Datasmith** on the main toolbar and select the exported `.udatasmith` file.
- Import both geometry and metadata into your destination folder (e.g., `/Game/Maps/Imported/`).

---

## Phase 3: Post-Import Python Automation (Unreal Engine)

Run a custom Unreal Python script to solve Source-specific engine translations and instantiate gameplay actors.

### 3.1 Textures and Materials Correction
- **Normal Map Orientation:** Scan all imported textures containing `_normal` suffixes or flagged as normal maps and set `flip_green_channel = True` to convert them from OpenGL to DirectX format.
- **Shaders Re-assignment:** Map Source textures (such as diffuse alpha or normal alpha specular masks) onto instances of your existing **Master PBR Materials** rather than generic Datasmith-generated materials.

### 3.2 Gameplay Entity Replacement (Spawns, Pickups, Cabinets)
- Scan all level actors for Datasmith metadata.
- Parse the `classname` parameter to map Source entities to custom UE4 Blueprints:
  - `info_player_teamspawn` / `info_player_start` $\rightarrow$ `BP_SpawnPoint`
  - `item_healthkit_*` $\rightarrow$ `BP_HealthPickup_*`
  - `item_ammopack_*` $\rightarrow$ `BP_AmmoPickup_*`
  - `func_regenerate` $\rightarrow$ `BP_ResupplyCabinet`
- **Metadata Propagation:**
  - Extract the `TeamNum` key (e.g., 2 for RED/Terrorists, 3 for BLU/Counter-Terrorists) and write it directly to the spawned blueprint's editable team variable.
  - Transfer `targetname` and `spawnflags` onto the target UE4 actors to feed gameplay event managers.
- **Clean up:** Delete original Datasmith placeholder actors from the level hierarchy.

### 3.3 Rebuilding the 3D Skybox
- Group all imported skybox assets (often identified by custom tags or small-scale properties near the map boundaries).
- Position and scale them dynamically relative to the main world bounds to act as functional sky backdrops.

---

## Automation Scripts Overview

### Unreal Post-Import Swapper (Pseudo-Python)
```python
import unreal

ENTITY_MAP = {
    "info_player_start": "/Game/Blueprints/Gameplay/BP_SpawnPoint.BP_SpawnPoint_C",
    "item_healthkit_small": "/Game/Blueprints/Pickups/BP_HealthPickup_Small.BP_HealthPickup_Small_C",
    "func_regenerate": "/Game/Blueprints/Gameplay/BP_ResupplyCabinet.BP_ResupplyCabinet_C"
}

def execute_port_cleanup():
    all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
    for actor in all_actors:
        metadata = unreal.DatasmithContentLibrary.get_datasmith_user_data(actor)
        if not metadata:
            continue
            
        classname = metadata.get_user_value("classname")
        if classname in ENTITY_MAP:
            bp_path = ENTITY_MAP[classname]
            bp_class = unreal.EditorAssetLibrary.load_blueprint_class(bp_path)
            
            # Spawn & configure
            loc = actor.get_actor_location()
            rot = actor.get_actor_rotation()
            new_actor = unreal.EditorLevelLibrary.spawn_actor_from_class(bp_class, loc, rot)
            
            # Assign team metadata
            team_num = metadata.get_user_value("TeamNum")
            if team_num and hasattr(new_actor, 'set_team'):
                new_actor.set_team(int(team_num))
                
            # Destroy placeholder
            unreal.EditorLevelLibrary.destroy_actor(actor)

execute_port_cleanup()
```
