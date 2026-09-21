import os
import logging
import tempfile

# Prevent OpenMP and MKL thread-pool deadlocks in local environments
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

def setup_logging():
    """
    Configures the global logging system to output to console and optionally conversion.log.
    Gracefully handles read-only filesystems (e.g. Vercel serverless functions).
    """
    root_logger = logging.getLogger()
    
    # If handlers are already set up (e.g. from reload), don't duplicate them
    if not root_logger.handlers:
        root_logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        # Stream / Console handler (Supported on Vercel stdout/stderr)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        
        # File handler (Safely attempt file logging, ignore on read-only filesystem)
        try:
            is_vercel = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
            log_dir = os.path.join(tempfile.gettempdir(), "logs") if is_vercel else "logs"
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "conversion.log")
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            root_logger.info(f"File logging disabled (read-only filesystem or serverless mode): {e}")
        
    logging.info("Logging configured successfully.")

