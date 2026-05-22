import os
import zipfile
import re
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"

# Files and directories to exclude from the addon zip package
EXCLUDE_PATTERNS = {
    r"^\.git",
    r"^\.github",
    r"^\.idea",
    r"^\.vscode",
    r"^__pycache__",
    r"\.pyc$",
    r"\.pyo$",
    r"\.DS_Store$",
    r"^dist",
    r"^scripts",
    r"^PORTING_PLAN\.md$",
    r"^tests",
    r"^TODO\.md$",
    r"^LICENSE$",
    r"^\.gitignore$"
}

def get_addon_version() -> str:
    """Parses __init__.py to retrieve the addon version."""
    init_file = ROOT_DIR / "__init__.py"
    if not init_file.exists():
        return "unknown"
        
    content = init_file.read_text(encoding="utf-8")
    # Search for "version": (x, y, z)
    match = re.search(r'"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', content)
    if match:
        return f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
    
    # Fallback to general tuple regex
    match = re.search(r'version.*?\(\s*([\d,\s]+)\s*\)', content)
    if match:
        version_tuple = match.group(1).replace(" ", "").split(",")
        return ".".join(version_tuple)
        
    return "unknown"

def should_exclude(rel_path: str) -> bool:
    """Determines if a given relative path matches any exclusion patterns."""
    normalized_path = rel_path.replace("\\", "/")
    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, normalized_path) or any(re.search(pattern, part) for part in normalized_path.split("/")):
            return True
    return False

def package_addon():
    version = get_addon_version()
    zip_name = f"SourceIO_v{version}.zip"
    
    # Ensure dist folder exists
    DIST_DIR.mkdir(exist_ok=True)
    zip_path = DIST_DIR / zip_name
    
    print(f"[+] Packaging SourceIO v{version}...")
    print(f"[+] Output: {zip_path}")
    
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        file_count = 0
        for root, dirs, files in os.walk(ROOT_DIR):
            # Resolve relative root
            rel_root = os.path.relpath(root, ROOT_DIR)
            
            # Prune directory search to speed up and honor exclusions
            if rel_root != "." and should_exclude(rel_root):
                dirs[:] = []  # Don't recurse into excluded directories
                continue
                
            for file in files:
                file_rel_path = os.path.join(rel_root, file) if rel_root != "." else file
                
                if should_exclude(file_rel_path):
                    continue
                
                # Blender requires the root zip folder to match the addon name (SourceIO)
                arcname = os.path.join("SourceIO", file_rel_path)
                real_filepath = os.path.join(root, file)
                
                zipf.write(real_filepath, arcname)
                file_count += 1
                
    print(f"[+] Successfully packaged {file_count} files into {zip_name}!")

if __name__ == "__main__":
    package_addon()
