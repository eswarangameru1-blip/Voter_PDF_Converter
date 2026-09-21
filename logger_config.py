import os
# Prevent OpenMP and MKL thread-pool deadlocks in local environments
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import logging

def setup_logging():
    """
    Configures the global logging system to output to both console and logs/conversion.log.
    """
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "conversion.log")
    
    # Get root logger
    root_logger = logging.getLogger()
    
    # If handlers are already set up (e.g. from reload), don't duplicate them
    if not root_logger.handlers:
        root_logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        # File handler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        
    logging.info("Logging configured successfully. Outputting to logs/conversion.log")
