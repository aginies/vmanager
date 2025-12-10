
import logging
from functools import wraps

def log_function_call(func):
    """
    A decorator that logs the function call and its arguments.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        logging.info(f"Calling {func.__name__} with args: {args}, kwargs: {kwargs}")
        try:
            result = func(*args, **kwargs)
            logging.info(f"{func.__name__} returned: {result}")
            return result
        except Exception as e:
            logging.error(f"Exception in {func.__name__}: {e}")
            raise
    return wrapper
