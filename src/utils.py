import hashlib
import os
import shutil

from .cache import write_text_atomic

def file_exists(filepath):
    """Convenience check if a filepath already exists."""
    return os.path.isfile(filepath)

def write_file(filepath, content):
    """Write content to a file."""
    write_text_atomic(filepath, content)

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

def _cache_directory_name(mkv_filename, source_path=None):
    if not source_path:
        return mkv_filename
    canonical_path = os.path.normcase(os.path.abspath(source_path))
    path_hash = hashlib.sha256(canonical_path.encode("utf-8")).hexdigest()[:12]
    return f"{mkv_filename}-{path_hash}"


def temp_dir(mkv_filename, source_path=None):
    """Get or create a temporary caching directory for a specific input file."""
    tmp_dir = os.path.join(".tmp", _cache_directory_name(mkv_filename, source_path))
    os.makedirs(tmp_dir, exist_ok=True)
    
    return tmp_dir

def clear_cache_for_file(mkv_filename, source_path=None):
    """Clear all cached files for a specific MKV file."""
    cache_dir = os.path.join(".tmp", _cache_directory_name(mkv_filename, source_path))
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir)
        print(f"[INFO] Cleared cache for '{mkv_filename}'")
    else:
        print(f"[INFO] No cache found for '{mkv_filename}'")

def get_optimal_device_and_model(force_cpu=False):
    """Determine the best device and model without importing torch at CLI startup."""
    import torch

    if not force_cpu and torch.cuda.is_available():
        device = "cuda"
        gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1e9
        if gpu_memory >= 8:
            model_name = "large-v3"
        elif gpu_memory >= 6:
            model_name = "medium"
        else:
            model_name = "small"
    else:
        device = "cpu"
        model_name = "medium"
    
    print(f"[INFO] Device: {device}, Model: {model_name}")
    return device, model_name


def get_gpu_memory_gb():
    """Return CUDA device memory, or zero when CUDA is unavailable."""
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).total_memory / 1e9
    except (ImportError, RuntimeError):
        pass
    return 0.0
