"""
Unreal Engine 4 Post-Import Map Swapper and Entity Cleaner Script
==================================================================
This script automates cleanups and blueprint conversions on maps imported via Datasmith:
1. Automatically identifies and destroys all redundant armature ('_arm') actors and 
   their corresponding world-origin child model duplicates.
2. Automatically replaces 'info_player_teamspawn' and 'info_player_start' actors with 
   your custom 'TF2_Spawn' blueprint, mapping team numbers correctly:
   - Source TeamNum 2 (RED) -> UE4 TeamNumber 2
   - Source TeamNum 3 (BLU) -> UE4 TeamNumber 1
   - Defaults other values -> UE4 TeamNumber 1

How to Run in Unreal Engine 4:
-----------------------------
1. Open your imported map level in the UE4 Editor.
2. Go to File -> Execute Python Script...
3. Select this script file: /Users/x390448/workspace/source-io/scripts/ue4_post_import.py
4. The post-import automation sequence will execute immediately!
"""

import unreal

def cleanup_armature_actors():
    """
    Scans the current active level and destroys all redundant armature ('_arm') parent actors 
    along with their world-origin child model duplicates.
    """
    print("[UE4 Post-Import] Step 1: Initiating armature and world-origin child actor cleanup...")
    all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
    destroyed_parent_count = 0
    destroyed_child_count = 0

    for actor in all_actors:
        # Check if actor is valid (not yet destroyed)
        if not actor:
            continue
            
        actor_name = actor.get_name()
        if "_arm" in actor_name.lower():
            # Find and destroy all attached child models at the world origin first
            attached_children = actor.get_attached_actors()
            for child in attached_children:
                if child:
                    child_name = child.get_name()
                    unreal.EditorLevelLibrary.destroy_actor(child)
                    destroyed_child_count += 1
                    print(f"[UE4 Post-Import] Destroyed duplicate world-origin child model: {child_name}")
            
            # Destroy the redundant armature parent actor itself
            unreal.EditorLevelLibrary.destroy_actor(actor)
            destroyed_parent_count += 1
            print(f"[UE4 Post-Import] Destroyed redundant parent armature actor: {actor_name}")

    print(f"[UE4 Post-Import] Step 1 Complete: Destroyed {destroyed_parent_count} armature parent actors and {destroyed_child_count} duplicate child models.")

def replace_spawn_points():
    """
    Scans the current active level, locates 'info_player_teamspawn' and 'info_player_start' actors,
    spawns the custom TF2_Spawn blueprint at their exact locations/rotations, maps the TeamNum 
    to the correct team number, and deletes the original Datasmith placeholders.
    """
    print("[UE4 Post-Import] Step 2: Initiating Spawn Point replacement...")
    
    blueprint_path = "/Game/tf2_commons_v142/Maps/Gamemodes/TF2_Spawn.TF2_Spawn_C"
    
    # Verify/Load the custom spawn point blueprint class
    try:
        spawn_blueprint_class = unreal.EditorAssetLibrary.load_blueprint_class(blueprint_path)
    except Exception as e:
        print(f"[UE4 Post-Import] ERROR: Failed to load Blueprint Class at {blueprint_path}. Make sure the asset exists. Error: {e}")
        return

    if not spawn_blueprint_class:
        print(f"[UE4 Post-Import] ERROR: Spawn Point Blueprint Class could not be loaded from path: {blueprint_path}")
        return

    all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
    replaced_count = 0

    for actor in all_actors:
        if not actor:
            continue

        actor_name = actor.get_name().lower()
        classname = ""

        # Retrieve classname from Datasmith User Data metadata
        datasmith_user_data = unreal.DatasmithContentLibrary.get_datasmith_user_data(actor)
        if datasmith_user_data:
            classname = unreal.DatasmithContentLibrary.get_datasmith_user_data_value_for_key(actor, "classname") or ""

        # Check if this actor represents a spawn point (using metadata or name fallback)
        is_spawn_point = ("info_player_teamspawn" in classname.lower() or 
                          "info_player_start" in classname.lower() or
                          "info_player_teamspawn" in actor_name or
                          "info_player_start" in actor_name)

        if is_spawn_point:
            # Extract transforms
            location = actor.get_actor_location()
            rotation = actor.get_actor_rotation()

            # Retrieve and map Source TeamNum to UE4 TeamNumber
            team_num_str = ""
            if datasmith_user_data:
                team_num_str = unreal.DatasmithContentLibrary.get_datasmith_user_data_value_for_key(actor, "TeamNum") or ""

            # Mapping logic:
            # Source TeamNum 2 (RED) -> UE4 TeamNumber 2
            # Source TeamNum 3 (BLU) -> UE4 TeamNumber 1
            # Defaults to BLU (1) for general info_player_start or fallback
            ue4_team_number = 1
            if team_num_str == "2":
                ue4_team_number = 2
            elif team_num_str == "3":
                ue4_team_number = 1

            # Spawn the custom TF2_Spawn blueprint
            try:
                new_spawn_actor = unreal.EditorLevelLibrary.spawn_actor_from_class(spawn_blueprint_class, location, rotation)
                if new_spawn_actor:
                    # Write the converted team coordinate to the editable variable on the spawned actor
                    new_spawn_actor.set_editor_property("TeamNumber", ue4_team_number)
                    
                    # Log the successful replacement
                    team_label = "RED (2)" if ue4_team_number == 2 else "BLU (1)"
                    print(f"[UE4 Post-Import] Replaced {actor.get_name()} with custom TF2_Spawn. Set TeamNumber to {team_label} (Source TeamNum was '{team_num_str}')")
                    
                    # Destroy the original Datasmith placeholder actor
                    unreal.EditorLevelLibrary.destroy_actor(actor)
                    replaced_count += 1
            except Exception as e:
                print(f"[UE4 Post-Import] Failed to replace spawn point actor {actor.get_name()}: {e}")

    print(f"[UE4 Post-Import] Step 2 Complete: Successfully replaced {replaced_count} spawn points with custom TF2_Spawn actors.")

def run_post_import_processor():
    """
    Runs the complete sequence of post-import processing tasks:
    1. Redundant armature cleanup
    2. Custom gameplay blueprint replacement
    """
    print("[UE4 Post-Import] Starting Post-Import Automation Sequence...")
    cleanup_armature_actors()
    replace_spawn_points()
    print("[UE4 Post-Import] Post-Import Automation Sequence completed successfully!")

# Execute automatically when the script is loaded via "File -> Execute Python Script..."
run_post_import_processor()
