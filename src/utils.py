import os
import shutil
import torch

def file_exists(filepath):
    """Convenience check if a filepath already exists."""
    return os.path.isfile(filepath)

def write_file(filepath, content):
    """Write content to a file."""
    if not file_exists(filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

def hex_to_binary(hex_string):
    """Converts a hex color string from RGB to BGR format and returns decimal.
    Input format: RRGGBB (RGB)
    Output format: Decimal value of BBGGRR (BGR)
    """
    if len(hex_string) != 6:
        return int(hex_string, 16)  # Non-color hex strings
        
    rr = hex_string[0:2]
    gg = hex_string[2:4]
    bb = hex_string[4:6]
    
    bgr_string = bb + gg + rr
    return int(bgr_string, 16)

def temp_dir(mkv_filename):
    """Get or create a temporary caching directory for a specific input file."""
    tmp_dir = os.path.join(".tmp", mkv_filename)
    os.makedirs(tmp_dir, exist_ok=True)
    
    return tmp_dir

def clear_cache_for_file(mkv_filename):
    """Clear all cached files for a specific MKV file."""
    cache_dir = temp_dir(mkv_filename)
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir)
        print(f"[INFO] Cleared cache for '{mkv_filename}'")
    else:
        print(f"[INFO] No cache found for '{mkv_filename}'")

def get_optimal_device_and_model(force_cpu=False):
    """Determine the best device and model configuration for any platform""" 
    if not(force_cpu) and torch.cuda.is_available():
        device = "cuda"
        gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1e9
        if gpu_memory >= 8:
            model_name = "large-v2"
        elif gpu_memory >= 6:
            model_name = "medium"
        else:
            model_name = "small"
    else:
        device = "cpu"
        model_name = "medium"
    
    print(f"[INFO] Device: {device}, Model: {model_name}")
    return device, model_name
